#!/usr/bin/env python
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
T78 = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(T78))
S3 = os.path.join(ROOT, "Step_4_Student")
SDG = os.path.join(ROOT, "Step_1_SDG", "sdg")
SHIPPED = os.path.join(ROOT, "Step_3_Teacher", "teacher_cache")
ARMS = ["nocontains", "noseq", "nocf", "nodd", "nogd", "nosd", "taint_only"]

for v in ("DROP_RELATIONS", "TAINT_ONLY_TEACHER", "TEACHER_NO_LIMIT_CHECKS"):
    os.environ.pop(v, None)
os.environ["SD_EDGE_WEIGHT"] = "0.7"          # read at import by the teacher
sys.path.insert(0, S3)
sys.path.insert(0, os.path.join(ROOT, "Step_3_Teacher"))

def _rebuild_one(name):
    import torch
    from teacher_taint_engine import SDGTaintEngine
    g = json.load(open(os.path.join(SDG, name + ".json")))
    fresh = SDGTaintEngine(g).run(max_iters=8)
    old = torch.load(os.path.join(SHIPPED, name + ".pt"), weights_only=False)
    return name, fresh == old

def _targets(d):
    return d["y_graph"], d["y_node"], d["history"]

def _effect_one(args):
    arm, name = args
    import torch
    a = torch.load(os.path.join(T78, "teacher_caches", arm, name + ".pt"), weights_only=False)
    b = torch.load(os.path.join(SHIPPED, name + ".pt"), weights_only=False)
    ya, na, ha = _targets(a)
    yb, nb, hb = _targets(b)
    return arm, name, ya != yb, na != nb, ha != hb, abs(ya - yb)

def main():
    names = sorted(f[:-5] for f in os.listdir(SDG) if f.endswith(".json"))
    assert len(names) == 753, len(names)
    out = {"n_graphs": len(names), "sd_edge_weight": "0.7"}

    with ProcessPoolExecutor(max_workers=int(os.environ.get("WORKERS", 16))) as ex:
        res = list(ex.map(_rebuild_one, names, chunksize=8))
    bad = [n for n, ok in res if not ok]
    out["rebuild_check"] = {"identical": len(names) - len(bad), "different": len(bad), "examples": bad[:10]}
    print(f"rebuild check: {len(names) - len(bad)}/{len(names)} entries identical to the shipped teacher_cache")

    rel_count = {}
    for n in names:
        types = {e["type"] for e in json.load(open(os.path.join(SDG, n + ".json")))["edges"]}
        for t in types:
            rel_count[t] = rel_count.get(t, 0) + 1

    out["effect_check"] = {}
    jobs = [(a, n) for a in ARMS if os.path.isfile(os.path.join(T78, "teacher_caches", a, "_PREBUILD_DONE"))
            for n in names]
    with ProcessPoolExecutor(max_workers=int(os.environ.get("WORKERS", 16))) as ex:
        eff = list(ex.map(_effect_one, jobs, chunksize=16))
    for arm in ARMS:
        rows = [r for r in eff if r[0] == arm]
        if not rows:
            continue
        rel = arm[2:] if arm.startswith("no") else None
        rec = {"graphs_y_graph_changed": sum(r[2] for r in rows),
               "graphs_y_node_changed": sum(r[3] for r in rows),
               "graphs_trajectory_changed": sum(r[4] for r in rows),
               "graphs_any_target_changed": sum(r[2] or r[3] or r[4] for r in rows),
               "mean_abs_delta_y_graph": sum(r[5] for r in rows) / len(rows)}
        if rel:
            rec["graphs_containing_relation"] = rel_count.get(rel, 0)
        out["effect_check"][arm] = rec
        print(f"  {arm:12s} targets changed on {rec['graphs_any_target_changed']:3d}/753 graphs"
              + (f"  ({rec['graphs_containing_relation']} graphs contain {rel})" if rel else ""))

    os.makedirs(os.path.join(T78, "results"), exist_ok=True)
    p = os.path.join(T78, "results", "TEACHER_CACHE_CHECK.json")
    json.dump(out, open(p, "w"), indent=1)
    print(f"written -> {os.path.relpath(p, ROOT)}")
    if bad:
        sys.exit(1)

if __name__ == "__main__":
    main()
