#!/usr/bin/env python
# build_sdg.py
# Pass 1: builds the SDG of every contract with its pinned solc version
# (solc_versions.csv) and applies the authorization post-pass. Output: ./sdg/
import csv, json, os, subprocess, sys
from collections import defaultdict
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
os.makedirs(OUT, exist_ok=True)
ENV = dict(os.environ, PATH=BIN + os.pathsep + os.environ.get("PATH", ""))

def sol(n):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{DATA}/{d}/{n}.sol"
        if os.path.exists(p):
            return p
    return None

jobs = {}
for i, row in enumerate(csv.reader(open(os.path.join(DATA, "solc_versions.csv")))):
    if i == 0 or len(row) < 2:
        continue
    p = sol(row[0])
    if p:
        jobs[row[0]] = (p, row[1])
print(f"{len(jobs)} contracts -> {OUT}", flush=True)

by_ver = defaultdict(list)
for n, (p, v) in jobs.items():
    by_ver[v].append((n, p))

def run_one(n, p, ver):
    dst = os.path.join(OUT, n + ".json")
    if os.path.exists(dst):
        return n, None
    try:
        subprocess.run([PY_EXE, GEN, p, ver], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, cwd=HERE, timeout=400, env=ENV)
    except Exception as e:
        return n, str(e)[:120]
    if not os.path.exists(dst):
        return n, "no output"
    try:
        g = json.load(open(dst)); auth_postpass.apply(g); json.dump(g, open(dst, "w"))
    except Exception as e:
        return n, f"postpass: {str(e)[:90]}"
    return n, None

done, fails = 0, {}
for ver in sorted(by_ver):
    subprocess.run([PY_EXE, os.path.join(BIN, "solc-select"), "use", ver, "--always-install"],
                   capture_output=True, text=True, env=ENV)
    with ThreadPoolExecutor(max_workers=14) as ex:
        for fut in as_completed([ex.submit(run_one, n, p, ver) for n, p in by_ver[ver]]):
            n, err = fut.result()
            if err: fails[n] = err
            else: done += 1
    print(f"  [solc {ver}] ok={done} fail={len(fails)}", flush=True)
json.dump(fails, open(os.path.join(HERE, "_fails.json"), "w"), indent=1)
print(f"\nSDGs: {done}/{len(jobs)}")
