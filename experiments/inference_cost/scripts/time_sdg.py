#!/usr/bin/env python
import json, os, platform, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
VF = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
S1 = os.path.join(VF, "Step_1_SDG")
sys.path.insert(0, S1)
import auth_postpass

D = os.path.join(VF, "Dataset", "FINAL_CLEAN_DATASET")
GEN = os.path.join(S1, "slither_sdg_generator.py")
PY = sys.executable
LADDER = ["0.4.26", "0.4.25", "0.4.24", "0.4.21", "0.4.19", "0.4.16",
          "0.5.17", "0.5.11", "0.6.12", "0.7.6", "0.8.20", "0.8.29"]   # compiler_ladder.py

TEST = json.load(open(os.path.join(D, "split.json")))["test"]
assert len(TEST) == 121
PIN = {}
for i, line in enumerate(open(os.path.join(D, "solc_versions.csv"))):
    p = line.strip().split(",")
    if i and len(p) >= 2:
        PIN[p[0]] = p[1]

def sol(n):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{D}/{d}/{n}.sol"
        if os.path.exists(p):
            return p
    raise FileNotFoundError(n)

def attempt(n, ver, work):
    env = dict(os.environ, SOLC_VERSION=ver,
               PATH=os.path.dirname(PY) + os.pathsep + os.environ.get("PATH", ""))
    dst = os.path.join(work, "sdg", n + ".json")
    t = time.perf_counter()
    try:
        subprocess.run([PY, GEN, sol(n), ver], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, cwd=work, env=env, timeout=400)
    except Exception:
        pass
    ok = os.path.exists(dst)
    if ok:
        try:
            g = json.load(open(dst)); auth_postpass.apply(g); json.dump(g, open(dst, "w"))
        except Exception:
            ok = False
    return time.perf_counter() - t, ok

def canon(g):
    return (sorted(json.dumps(x, sort_keys=True) for x in g["nodes"]),
            sorted(json.dumps(x, sort_keys=True) for x in g["edges"]))

base = []
for _ in range(3):
    t = time.perf_counter()
    subprocess.run([PY, "-c", f"import sys; sys.path.insert(0, {S1!r}); import slither_sdg_core"],
                   capture_output=True, cwd=S1)
    base.append(time.perf_counter() - t)

work = tempfile.mkdtemp(prefix="sdg_timing_")
rows = []
for i, n in enumerate(TEST, 1):
    tried, total, used = [], 0.0, None
    for ver in [PIN[n]] + [v for v in LADDER if v != PIN[n]]:
        dt, ok = attempt(n, ver, work)
        tried.append([ver, dt, ok]); total += dt
        if ok:
            used = ver
            break
    match = None
    if used:
        match = canon(json.load(open(os.path.join(work, "sdg", n + ".json")))) == \
                canon(json.load(open(os.path.join(S1, "sdg", n + ".json"))))
    rows.append({"name": n, "pinned": PIN[n], "version_used": used, "seconds": total,
                 "first_attempt_seconds": tried[0][1], "attempts": tried,
                 "matches_shipped_sdg": match})
    print(f"[{i:3d}/121] {n:45s} {total*1000:9.1f} ms  ver={used}  match={match}", flush=True)

json.dump({"host": platform.node(), "python": sys.version, "work_dir": work,
           "interpreter_import_baseline_seconds": base, "rows": rows},
          open(sys.argv[1], "w"), indent=1)
print("WROTE", sys.argv[1])
