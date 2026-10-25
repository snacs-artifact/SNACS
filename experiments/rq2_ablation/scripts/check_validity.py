#!/usr/bin/env python
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
T78 = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(T78))
S3 = os.path.join(ROOT, "Step_4_Student")
SLOTS = [201, 202, 203, 204, 205]
ARMS = ["nocontains", "noseq", "nocf", "nodd", "nogd", "nosd", "taint_only", "wo_teachersup",
        "wo_graph_teacher", "wo_node", "wo_traj", "wo_maskedstruct", "ctrl_full", "ctrl_from_s0", "ctrl_from_s1"]

def slot_map(arm):
    p = os.path.join(T78, "runs", arm, "SEEDS.json")
    if os.path.exists(p):
        return {int(k): int(v) for k, v in json.load(open(p))["slots"].items()}
    return {s: s for s in SLOTS}

def check_run(job):
    arm, seed = job
    run = os.path.join(T78, "runs", arm, f"final_init{seed}")
    ck = os.path.join(run, "stage2", "stage2_best.pt")
    done = os.path.join(T78, "logs", arm, f"s{seed}", "stage2.log")
    if not (os.path.exists(ck) and os.path.exists(done) and "TEST EVALUATION" in open(done, errors="replace").read()):
        return {"arm": arm, "seed": seed, "status": "incomplete"}
    env = json.load(open(os.path.join(run, "ARM.json"))).get("env", {})
    for v in ("DROP_RELATIONS", "ABLATE_LOSS", "TAINT_ONLY_TEACHER", "V9_INVERSE"):
        os.environ.pop(v, None)
    os.environ.update(env)                         # read at call time by filter_pyg_edges
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["V7_CODEBERT_DIR"] = os.path.join(ROOT, "Step_2_Preprocessing", "codebert_final")
    os.environ["V7_TEXT_PROJ"] = "128"
    sys.path.insert(0, S3)
    import torch
    torch.set_num_threads(1)
    from utils.ablation import filter_pyg_edges, pinned_edge_type_mapping
    from utils.model import RelationalGNN
    from utils.text_features import forward_with_text

    D = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
    val = json.load(open(f"{D}/split.json"))["val"]           # validation contracts only
    lab = {}
    for line in open(f"{D}/labels.csv"):
        q = line.strip().split(",")
        if len(q) >= 2 and q[1] in ("0", "1"):
            lab[q[0]] = int(q[1])
    enc = os.path.join(ROOT, "Step_2_Preprocessing", "encoded_pyg")
    c = torch.load(ck, map_location="cpu", weights_only=False)
    cfg = c["config"]
    g0 = torch.load(f"{enc}/{val[0]}.pt", map_location="cpu", weights_only=False)
    m = RelationalGNN(in_dim=g0.x.shape[1], hidden_dim=cfg.get("hidden_dim", 256),
                      edge_types=pinned_edge_type_mapping(), text_dim=768, text_proj_dim=128)
    m.load_state_dict(c["model"])
    m.eval()
    sc = []
    with torch.no_grad():
        for n in val:
            g = filter_pyg_edges(torch.load(f"{enc}/{n}.pt", map_location="cpu", weights_only=False))
            sc.append(float(m.graph_score(forward_with_text(m, g, K=cfg["K"], name=n)).item()))
    y = [lab[n] for n in val]
    P = [s for s, t in zip(sc, y) if t == 1]
    N = [s for s, t in zip(sc, y) if t == 0]
    auc = sum((i > j) + 0.5 * (i == j) for i in P for j in N) / (len(P) * len(N))
    one_side = all(s > 0.5 for s in sc) or all(s <= 0.5 for s in sc)
    failed = abs(auc - 0.5) < 1e-12 and one_side
    return {"arm": arm, "seed": seed, "status": "FAILED" if failed else "valid", "val_auc": auc,
            "val_score_min": min(sc), "val_score_max": max(sc), "one_class_prediction": one_side}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    if not a.all:
        r = check_run((a.arm, a.seed))
        print(json.dumps(r))
        sys.exit({"valid": 0, "FAILED": 3}.get(r["status"], 2))

    jobs, slot_of = [], {}
    for arm in ARMS:
        for slot, seed in slot_map(arm).items():
            jobs.append((arm, seed))
            slot_of[(arm, seed)] = slot
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(check_run, jobs))
    for r in res:
        r["slot"] = slot_of[(r["arm"], r["seed"])]
    os.makedirs(os.path.join(T78, "results"), exist_ok=True)
    json.dump({"criterion": "validation AUC exactly 0.5 and every validation score on one side of 0.5",
               "data": "validation split only (108 contracts)", "runs": res},
              open(os.path.join(T78, "results", "VALIDITY_CHECK.json"), "w"), indent=1)
    bad = [r for r in res if r["status"] != "valid"]
    print(f"validity: {len(res) - len(bad)}/{len(res)} runs valid", file=sys.stderr)
    for r in bad:
        print(f"{r['arm']} {r['slot']}")                      # stdout: the runs the rule must handle
        print(f"  {r['arm']} slot {r['slot']} seed {r['seed']}: {r['status']}", file=sys.stderr)
    sys.exit(3 if bad else 0)

if __name__ == "__main__":
    main()
