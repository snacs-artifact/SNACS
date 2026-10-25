#!/usr/bin/env python
import argparse
import json
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
S3 = os.path.join(ROOT, "Step_4_Student")
DATA = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")

ap = argparse.ArgumentParser()
ap.add_argument("--checkpoints", required=True, help="dir holding final_init<seed>/stage2/stage2_best.pt")
ap.add_argument("--split-file", default=os.path.join(DATA, "split.json"))
ap.add_argument("--seeds", default="201,202,203,204,205")
ap.add_argument("--threshold", type=float, default=0.5)
ap.add_argument("--label", default=None)
ap.add_argument("--bootstrap", type=int, default=10000)
ap.add_argument("--bootstrap-seed", type=int, default=22)
ap.add_argument("--out", required=True)
a = ap.parse_args()
CKPT = a.checkpoints if os.path.isabs(a.checkpoints) else os.path.join(ROOT, a.checkpoints)
SPLIT = a.split_file if os.path.isabs(a.split_file) else os.path.join(ROOT, a.split_file)
SEEDS = [int(s) for s in a.seeds.split(",")]
LABEL = a.label or os.path.basename(CKPT.rstrip("/"))

for v in ("DROP_RELATIONS", "ABLATE_LOSS", "TAINT_ONLY_TEACHER", "V9_INVERSE"):
    os.environ.pop(v, None)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["V7_CODEBERT_DIR"] = os.path.join(ROOT, "Step_2_Preprocessing", "codebert_final")
os.environ["V7_TEXT_PROJ"] = "128"
sys.path.insert(0, S3)

import torch  # noqa: E402
torch.set_num_threads(1)
from sklearn.metrics import average_precision_score  # noqa: E402
from utils.ablation import pinned_edge_type_mapping  # noqa: E402
from utils.model import RelationalGNN  # noqa: E402
from utils.text_features import forward_with_text, load_text_emb  # noqa: E402

sp = json.load(open(SPLIT))
lab = {}
for line in open(f"{DATA}/labels.csv"):
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
    auc = sum((i > j) + 0.5 * (i == j) for i in P for j in N) / (len(P) * len(N)) if P and N else 0.0
    return {"f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, "precision": pr, "recall": rc,
            "accuracy": (tp + tn) / len(y), "auc": auc,
            "pr_auc": float(average_precision_score(y, p)),
            "TP": tp, "FP": fp, "FN": fn, "TN": tn}

def prf_of(p, y, thr):
    tp = sum(1 for s, t in zip(p, y) if s > thr and t == 1)
    fp = sum(1 for s, t in zip(p, y) if s > thr and t == 0)
    fn = sum(1 for s, t in zip(p, y) if s <= thr and t == 1)
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return pr, rc, (2 * pr * rc / (pr + rc) if pr + rc else 0.0)

def bootstrap_ci(p, y, thr, n, seed):
    rng = random.Random(seed)
    m = len(y)
    draws = ([], [], [])
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        for col, v in zip(draws, prf_of([p[i] for i in idx], [y[i] for i in idx], thr)):
            col.append(v)
    out = {}
    for key, col in zip(("precision", "recall", "f1"), draws):
        col.sort()
        out[key] = [col[int(0.025 * n)], col[int(0.975 * n) - 1]]
    return out

models, Ks, cfgs = {}, set(), []
probe = torch.load(f"{ENC}/{sp['test'][0]}.pt", map_location="cpu", weights_only=False)
e = load_text_emb(os.environ["V7_CODEBERT_DIR"], sp["test"][0], probe.x.shape[0])
assert float(e.abs().sum()) > 0, "CodeBERT features are all zero"
for s in SEEDS:
    c = torch.load(f"{CKPT}/final_init{s}/stage2/stage2_best.pt", map_location="cpu", weights_only=False)
    cfg = c.get("config", {}) or {}
    assert "K" in cfg, f"seed {s}: checkpoint config has no K"
    Ks.add(cfg["K"])
    cfgs.append({"seed": s, "lr": cfg.get("lr"), "hidden_dim": cfg.get("hidden_dim"), "K": cfg["K"]})
    m = RelationalGNN(in_dim=probe.x.shape[1], hidden_dim=cfg.get("hidden_dim", 256),
                      edge_types=pinned_edge_type_mapping(), text_dim=768, text_proj_dim=128)
    m.load_state_dict(c["model"])
    m.eval()
    models[s] = (m, cfg["K"])
assert Ks == {2}, f"{LABEL}: expected K=2 on every seed, got {Ks}"
lrs = {c["lr"] for c in cfgs}
assert len(lrs) == 1, f"{LABEL}: seeds disagree on lr: {lrs}"

out = {"label": LABEL, "checkpoints": os.path.relpath(CKPT, ROOT),
       "split_file": os.path.relpath(SPLIT, ROOT), "seeds": SEEDS,
       "threshold": a.threshold, "K": 2, "lr": cfgs[0]["lr"],
       "split_counts": {k: len(sp[k]) for k in ("train", "val", "test")},
       "checkpoint_configs": cfgs}
for part in ("val", "test"):
    names = sp[part]
    y = [lab[n] for n in names]
    gs = {n: torch.load(f"{ENC}/{n}.pt", map_location="cpu", weights_only=False) for n in names}
    per = []
    for s in SEEDS:
        m, K = models[s]
        with torch.no_grad():
            per.append([float(m.graph_score(forward_with_text(m, gs[n], K=K, name=n)).item()) for n in names])
    ens = [st.mean(col) for col in zip(*per)]
    seed_m = [metrics(p, y, a.threshold) for p in per]
    r = metrics(ens, y, a.threshold)
    out[part] = {"n": len(names), "n_pos": sum(y), "ensemble": r,
                 "ci95": bootstrap_ci(ens, y, a.threshold, a.bootstrap, a.bootstrap_seed),
                 "per_seed_f1": [x["f1"] for x in seed_m],
                 "per_seed_auc": [x["auc"] for x in seed_m],
                 "mean_of_runs_f1": st.mean(x["f1"] for x in seed_m),
                 "sd_of_runs_f1": st.stdev(x["f1"] for x in seed_m) if len(seed_m) > 1 else 0.0,
                 "scores": dict(zip(names, ens)),
                 "per_seed_scores": {str(s): dict(zip(names, p)) for s, p in zip(SEEDS, per)}}
    print(f"[{LABEL}] {part.upper():4s} n={len(names):3d}  F1 {r['f1']:.4f}  P {r['precision']:.4f}  "
          f"R {r['recall']:.4f}  Acc {r['accuracy']:.4f}  AUC {r['auc']:.4f}  "
          f"TP/FP/FN/TN {r['TP']}/{r['FP']}/{r['FN']}/{r['TN']}  "
          f"per-seed F1 {[round(x, 4) for x in out[part]['per_seed_f1']]}", flush=True)

p = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
json.dump(out, open(p, "w"), indent=1)
print(f"[{LABEL}] written -> {os.path.relpath(p, ROOT)}")
