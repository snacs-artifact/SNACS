#!/usr/bin/env python
import argparse, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("V7_CODEBERT_DIR", os.path.join(ROOT, "Step_2_Preprocessing", "codebert_final"))
os.environ.setdefault("V7_TEXT_PROJ", "128")
import torch; torch.set_num_threads(1)
from sklearn.metrics import average_precision_score
from utils.ablation import pinned_edge_type_mapping
from utils.model import RelationalGNN
from utils.text_features import forward_with_text, load_text_emb

ap = argparse.ArgumentParser()
ap.add_argument("--split", choices=["test", "val", "both"], default="both")
ap.add_argument("--seeds", default="201,202,203,204,205")
ap.add_argument("--threshold", type=float, default=0.5)
ap.add_argument("--checkpoints", default=os.path.join(ROOT, "checkpoints_final"),
                help="directory holding final_init<seed>/stage2/stage2_best.pt "
                     "(default: the shipped SNACS/checkpoints_final)")
ap.add_argument("--out", default=os.path.join(HERE, "FINAL_RESULT.json"))
a = ap.parse_args()
SEEDS = [int(s) for s in a.seeds.split(",")]
CKPT = os.path.abspath(a.checkpoints)

D = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
sp = json.load(open(f"{D}/split.json"))
assert (len(sp["train"]), len(sp["val"]), len(sp["test"])) == (524, 108, 121)
assert not (set(sp["train"]) & set(sp["test"])) and not (set(sp["val"]) & set(sp["test"]))
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
    pr = tp/(tp+fp) if tp+fp else 0.0; rc = tp/(tp+fn) if tp+fn else 0.0
    P = [s for s, t in zip(p, y) if t == 1]; N = [s for s, t in zip(p, y) if t == 0]
    auc = sum((i > j) + 0.5*(i == j) for i in P for j in N)/(len(P)*len(N))
    return {"f1": 2*pr*rc/(pr+rc) if pr+rc else 0.0, "precision": pr, "recall": rc,
            "accuracy": (tp+tn)/len(y), "auc": auc, "pr_auc": float(average_precision_score(y, p)),
            "TP": tp, "FP": fp, "FN": fn, "TN": tn}

def run(part):
    names = sp[part]; y = [lab[n] for n in names]
    probe = torch.load(f"{ENC}/{names[0]}.pt", map_location="cpu", weights_only=False)
    e = load_text_emb(os.environ["V7_CODEBERT_DIR"], names[0], probe.x.shape[0])
    assert float(e.abs().sum()) > 0, (
        "CodeBERT features are all zero -- run Step_2_Preprocessing/codebert_embed.py "
        "first (V7_CODEBERT_DIR=%s)" % os.environ["V7_CODEBERT_DIR"])
    per = []; Ks = set()
    for s in SEEDS:
        c = torch.load(f"{CKPT}/final_init{s}/stage2/stage2_best.pt",
                       map_location="cpu", weights_only=False)
        cfg = c.get("config", {}) or {}
        assert "K" in cfg, f"seed {s}: checkpoint config has no K; refusing to guess"
        Ks.add(cfg["K"])
        m = RelationalGNN(in_dim=probe.x.shape[1], hidden_dim=cfg.get("hidden_dim", 256),
                          edge_types=pinned_edge_type_mapping(), text_dim=768, text_proj_dim=128)
        m.load_state_dict(c["model"]); m.eval()
        with torch.no_grad():
            per.append([float(m.graph_score(forward_with_text(
                m, torch.load(f"{ENC}/{n}.pt", map_location="cpu", weights_only=False),
                K=cfg["K"], name=n)).item()) for n in names])
        print(f"  seed {s} scored (K={cfg['K']}, F1 {metrics(per[-1], y, a.threshold)['f1']:.4f})", flush=True)
    assert len(Ks) == 1, f"seeds disagree on K: {Ks}"
    K = next(iter(Ks))
    f1s = [metrics(p, y, a.threshold)["f1"] for p in per]
    ens = [st.mean(col) for col in zip(*per)]
    r = metrics(ens, y, a.threshold)
    print("=" * 72)
    print(f"{part.upper()}  n={len(names)}  ({sum(y)} vulnerable, {len(y)-sum(y)} safe)  thr={a.threshold}  K={K}")
    print("=" * 72)
    print(f"  per-seed F1  : {[round(x,4) for x in f1s]}")
    print(f"  mean of runs : {st.mean(f1s):.4f} +/- {st.stdev(f1s):.4f}")
    print(f"  ENSEMBLE     : F1 {r['f1']:.4f}  P {r['precision']:.4f}  R {r['recall']:.4f}  "
          f"Acc {r['accuracy']:.4f}  AUC {r['auc']:.4f}  PR-AUC {r['pr_auc']:.4f}")
    print(f"                 TP {r['TP']}  FP {r['FP']}  FN {r['FN']}  TN {r['TN']}\n")
    return {"n": len(names), "K": K, "ensemble": r, "per_seed_f1": f1s,
            "mean_of_runs": st.mean(f1s), "sd": st.stdev(f1s),
            "scores": {n: v for n, v in zip(names, ens)}}

out = {"checkpoints": os.path.relpath(CKPT, ROOT), "threshold": a.threshold, "seeds": SEEDS}
for part in (["val", "test"] if a.split == "both" else [a.split]):
    out[part] = run(part)
json.dump(out, open(a.out, "w"), indent=1)
print(f"written -> {a.out}")

