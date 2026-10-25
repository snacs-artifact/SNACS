#!/usr/bin/env python
# compiler_ladder.py
# Pass 2: retries every contract still missing an SDG with the compiler versions
# in LADDER, in order, and keeps the first version that works. Output: ./sdg/
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import auth_postpass

PY_EXE = sys.executable
BIN = os.path.dirname(PY_EXE)
GEN = os.path.join(HERE, "slither_sdg_generator.py")
DATA = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
OUT = os.path.join(HERE, "sdg")
ENV = dict(os.environ, PATH=BIN + os.pathsep + os.environ.get("PATH", ""))

# the exact ladder used to build the shipped graphs
LADDER = ["0.4.26", "0.4.25", "0.4.24", "0.4.21", "0.4.19", "0.4.16",
          "0.5.17", "0.5.11", "0.6.12", "0.7.6", "0.8.20", "0.8.29"]

split = json.load(open(os.path.join(DATA, "split.json")))
names = sorted(n for k in ("train", "val", "test") for n in split[k])
assert len(names) == 753, len(names)

def sol(n):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{DATA}/{d}/{n}.sol"
        if os.path.exists(p):
            return p
    return None

missing = [n for n in names if not os.path.exists(f"{OUT}/{n}.json")]
print(f"{len(names)} contracts, {len(missing)} still missing an SDG", flush=True)
recovered = {}

def attempt(n):
    p = sol(n)
    if not p:
        return n, False
    try:
        subprocess.run([PY_EXE, GEN, p], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, cwd=HERE, timeout=400, env=ENV)
    except Exception:
        return n, False
    dst = f"{OUT}/{n}.json"
    if not os.path.exists(dst):
        return n, False
    try:
        g = json.load(open(dst)); auth_postpass.apply(g); json.dump(g, open(dst, "w"))
    except Exception:
        os.remove(dst)          # incomplete output only; the .sol is untouched
        return n, False
    return n, True

for ver in LADDER:
    if not missing:
        break
    subprocess.run([PY_EXE, os.path.join(BIN, "solc-select"), "use", ver, "--always-install"],
                   capture_output=True, text=True, env=ENV)
    got = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for fut in as_completed([ex.submit(attempt, n) for n in missing]):
            n, ok = fut.result()
            if ok:
                recovered[n] = ver
                got.append(n)
    missing = [n for n in missing if n not in recovered]
    print(f"  [ladder {ver}] recovered {len(got):3d}   still missing {len(missing)}", flush=True)

json.dump({"recovered": recovered, "unrecovered": sorted(missing)},
          open(os.path.join(HERE, "_ladder_report.json"), "w"), indent=1)
print(f"\nladder recovered {len(recovered)}; unrecovered {len(missing)}")
print(f"total SDGs now: {len([n for n in names if os.path.exists(f'{OUT}/{n}.json')])}/753")
