#!/usr/bin/env python
import argparse
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
T78 = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(T78))
S3 = os.path.join(ROOT, "Step_4_Student")

ap = argparse.ArgumentParser()
ap.add_argument("--arm", required=True)
ap.add_argument("--seeds", default=None,
                help="default: the arm's five slots, from runs/<arm>/SEEDS.json if a seed was "
                     "replaced by the validity rule, else 201-205")
ap.add_argument("--threshold", type=float, default=0.5)
ap.add_argument("--out", default=None, help="default: experiments/rq2_ablation/results/arms/<arm>.json")
a = ap.parse_args()
CKPT = os.path.join(ROOT, "checkpoints_final") if a.arm == "full_shipped" else os.path.join(T78, "runs", a.arm)
if a.seeds:
    SEEDS = [int(s) for s in a.seeds.split(",")]
elif os.path.exists(os.path.join(CKPT, "SEEDS.json")):
    _slots = json.load(open(os.path.join(CKPT, "SEEDS.json")))["slots"]
    SEEDS = [int(_slots[k]) for k in sorted(_slots)]
else:
    SEEDS = [201, 202, 203, 204, 205]

for v in ("DROP_RELATIONS", "ABLATE_LOSS", "TAINT_ONLY_TEACHER", "V9_INVERSE"):
    os.environ.pop(v, None)
ARM_ENV = {}
if a.arm != "full_shipped":
    recs = [json.load(open(os.path.join(CKPT, f"final_init{s}", "ARM.json"))) for s in SEEDS]
    envs = {json.dumps(r.get("env", {}), sort_keys=True) for r in recs}
    assert len(envs) == 1, f"seeds of {a.arm} disagree on their switches: {envs}"
    ARM_ENV = recs[0].get("env", {})
    os.environ.update(ARM_ENV)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["V7_CODEBERT_DIR"] = os.path.join(ROOT, "Step_2_Preprocessing", "codebert_final")
os.environ["V7_TEXT_PROJ"] = "128"
sys.path.insert(0, S3)

import torch  # noqa: E402
torch.set_num_threads(1)
from sklearn.metrics import average_precision_score  # noqa: E402
from utils.ablation import RELATION_NAMES, dropped_relations, filter_pyg_edges, pinned_edge_type_mapping  # noqa: E402
from utils.model import RelationalGNN  # noqa: E402
from utils.text_features import forward_with_text, load_text_emb  # noqa: E402

D = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
sp = json.load(open(f"{D}/split.json"))
assert (len(sp["train"]), len(sp["val"]), len(sp["test"])) == (524, 108, 121)
lab = {}
for line in open(f"{D}/labels.csv"):
    p = line.strip().split(",")
    if len(p) >= 2 and p[1] in ("0", "1"):
        lab[p[0]] = int(p[1])
ENC = os.path.join(ROOT, "Step_2_Preprocessing", "encoded_pyg")

def metrics(p, y, thr):
    tp = sum(1 for s, t in zip(p, y) if s > thr and t == 1)
    fp = sum(1 for s, t in zip(p, y) if s > thr and t == 0)
    fn = sum(1 for s, t in zip(p, y) if s <= thr and t == 1)
    tn = sum(1 for s, t in zip(p, y) if s <= thr and t == 0)
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    P = [s for s, t in zip(p, y) if t == 1]
    N = [s for s, t in zip(p, y) if t == 0]
    auc = sum((i > j) + 0.5 * (i == j) for i in P for j in N) / (len(P) * len(N))
    return {"f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, "precision": pr, "recall": rc,
            "accuracy": (tp + tn) / len(y), "auc": auc, "pr_auc": float(average_precision_score(y, p)),
            "TP": tp, "FP": fp, "FN": fn, "TN": tn}

def graph(n):
    d = torch.load(f"{ENC}/{n}.pt", map_location="cpu", weights_only=False)
    return filter_pyg_edges(d)          # no-op unless the arm drops a relation

models, Ks = {}, set()
probe = torch.load(f"{ENC}/{sp['test'][0]}.pt", map_location="cpu", weights_only=False)
e = load_text_emb(os.environ["V7_CODEBERT_DIR"], sp["test"][0], probe.x.shape[0])
assert float(e.abs().sum()) > 0, "CodeBERT features are all zero"
for s in SEEDS:
    c = torch.load(f"{CKPT}/final_init{s}/stage2/stage2_best.pt", map_location="cpu", weights_only=False)
    cfg = c.get("config", {}) or {}
    assert "K" in cfg, f"seed {s}: checkpoint config has no K"
    Ks.add(cfg["K"])
    m = RelationalGNN(in_dim=probe.x.shape[1], hidden_dim=cfg.get("hidden_dim", 256),
                      edge_types=pinned_edge_type_mapping(), text_dim=768, text_proj_dim=128)
    m.load_state_dict(c["model"])
    m.eval()
    models[s] = (m, cfg["K"])
assert Ks == {2}, f"{a.arm}: expected K=2 on every seed, got {Ks}"

out = {"arm": a.arm, "checkpoints": os.path.relpath(CKPT, ROOT), "seeds": SEEDS,
       "threshold": a.threshold, "K": 2, "arm_env": ARM_ENV, "dropped_relations": dropped_relations()}
for part in ("val", "test"):
    names = sp[part]
    y = [lab[n] for n in names]
    gs = {n: graph(n) for n in names}
    edges = torch.stack([torch.bincount(gs[n].edge_type, minlength=6) for n in names]).sum(0).tolist()
    per = []
    for s in SEEDS:
        m, K = models[s]
        with torch.no_grad():
            per.append([float(m.graph_score(forward_with_text(m, gs[n], K=K, name=n)).item()) for n in names])
    ens = [st.mean(col) for col in zip(*per)]
    seed_m = [metrics(p, y, a.threshold) for p in per]
    out[part] = {"n": len(names), "n_pos": sum(y), "ensemble": metrics(ens, y, a.threshold),
                 "per_seed_f1": [r["f1"] for r in seed_m], "per_seed_auc": [r["auc"] for r in seed_m],
                 "mean_of_runs_f1": st.mean(r["f1"] for r in seed_m),
                 "sd_of_runs_f1": st.stdev(r["f1"] for r in seed_m) if len(seed_m) > 1 else 0.0,
                 "edges_per_relation": dict(zip(RELATION_NAMES, edges)),
                 "scores": dict(zip(names, ens)),
                 "per_seed_scores": {str(s): dict(zip(names, p)) for s, p in zip(SEEDS, per)}}
    r = out[part]["ensemble"]
    print(f"[{a.arm}] {part.upper():4s} n={len(names)}  F1 {r['f1']:.4f}  P {r['precision']:.4f}  "
          f"R {r['recall']:.4f}  AUC {r['auc']:.4f}  TP/FP/FN/TN {r['TP']}/{r['FP']}/{r['FN']}/{r['TN']}  "
          f"per-seed F1 {[round(x, 4) for x in out[part]['per_seed_f1']]}", flush=True)

p = a.out or os.path.join(T78, "results", "arms", f"{a.arm}.json")
os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
json.dump(out, open(p, "w"), indent=1)
print(f"[{a.arm}] written -> {os.path.relpath(p, ROOT)}")
