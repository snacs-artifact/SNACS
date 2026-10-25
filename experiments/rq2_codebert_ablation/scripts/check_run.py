#!/usr/bin/env python
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  (verifies the frozen protocol on import)

def check(job):
    arm, seed = job
    d = C.run_dir(arm, seed)
    if not C.run_complete(arm, seed):
        return {"arm": arm, "seed": seed, "status": "incomplete"}
    for s in (0, 1, 2):
        p = C.check_checkpoint(arm, os.path.join(d, f"stage{s}", f"stage{s}_best.pt"))
        if p:
            return {"arm": arm, "seed": seed, "status": "wrong_architecture", "problem": p}
    rec = json.load(open(os.path.join(d, "ARM.json")))
    if rec["codebert_branch"] != C.has_branch(arm):
        return {"arm": arm, "seed": seed, "status": "wrong_architecture", "problem": "ARM.json disagrees"}
    names, y = C.split_and_labels("val")
    m, K = C.load_model(arm, seed)
    sc = C.score(arm, m, K, names)
    a = C.auc(sc, y)
    one_side = all(s > C.THR for s in sc) or all(s <= C.THR for s in sc)
    collapsed = abs(a - 0.5) < 1e-12 and one_side
    return {"arm": arm, "seed": seed, "status": "collapsed" if collapsed else "valid", "val_auc": a,
            "one_side_prediction": one_side}

CODE = {"valid": 0, "incomplete": 2, "collapsed": 3, "wrong_architecture": 4}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=C.ARMS)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if not a.all:
        r = check((a.arm, a.seed))
        print(json.dumps(r))
        sys.exit(CODE[r["status"]])
    jobs = [(arm, s) for arm in C.ARMS for s in C.slot_seeds(arm)]
    with ProcessPoolExecutor(max_workers=10) as ex:
        res = list(ex.map(check, jobs))
    for r in res:
        r["slot"] = C.PROTO["slots"][C.slot_seeds(r["arm"]).index(r["seed"])]
    os.makedirs(C.RES, exist_ok=True)
    json.dump({"data": "validation split only", "runs": res}, open(os.path.join(C.RES, "VALIDITY_CHECK.json"), "w"), indent=1)
    for r in res:
        if r["status"] == "collapsed":
            print(f"{r['arm']} {r['slot']}")
        print(f"  {r['arm']} seed {r['seed']}: {r['status']}", file=sys.stderr)
    sys.exit(max(CODE[r["status"]] for r in res))

if __name__ == "__main__":
    main()
