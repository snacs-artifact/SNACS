import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EXP))
S3 = os.path.join(ROOT, "Step_4_Student")
RES = os.path.join(EXP, "results")
ENC = os.path.join(ROOT, "Step_2_Preprocessing", "encoded_pyg")
CODEBERT = os.path.join(ROOT, "Step_2_Preprocessing", "codebert_final")
ARMS = ["nocodebert", "ctrl_codebert"]

def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def verify_protocol():
    for line in open(os.path.join(EXP, "PROTOCOL.sha256")):
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            if sha256(os.path.join(EXP, parts[1])) != parts[0]:
                raise SystemExit(f"PROTOCOL VIOLATION: {parts[1]} changed after the freeze")
    return json.load(open(os.path.join(EXP, "protocol.json")))

PROTO = verify_protocol()
THR = PROTO["threshold"]

def has_branch(arm):
    return PROTO["arms"][arm]["codebert_branch"]

def slot_seeds(arm):
    p = os.path.join(EXP, "runs", arm, "SEEDS.json")
    if os.path.exists(p):
        slots = json.load(open(p))["slots"]
        return [int(slots[str(s)]) for s in PROTO["slots"]]
    return list(PROTO["slots"])

def use_arm(arm):
    for v in ("V7_CODEBERT_DIR", "V7_TEXT_PROJ", "V7_TEXT_DIM", "DROP_RELATIONS", "ABLATE_LOSS",
              "TAINT_ONLY_TEACHER", "V9_INVERSE"):
        os.environ.pop(v, None)
    if has_branch(arm):
        os.environ["V7_CODEBERT_DIR"] = CODEBERT
        os.environ["V7_TEXT_PROJ"] = "128"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if S3 not in sys.path:
        sys.path.insert(0, S3)

def split_and_labels(part):
    D = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
    names = json.load(open(os.path.join(D, "split.json")))[part]
    lab = {}
    for line in open(os.path.join(D, "labels.csv")):
        q = line.strip().split(",")
        if len(q) >= 2 and q[1] in ("0", "1"):
            lab[q[0]] = int(q[1])
    return names, [lab[n] for n in names]

def run_dir(arm, seed):
    return os.path.join(EXP, "runs", arm, f"final_init{seed}")

def run_complete(arm, seed):
    d = run_dir(arm, seed)
    return all(os.path.exists(os.path.join(d, f"stage{s}", ".done")) for s in (0, 1, 2))

def check_checkpoint(arm, path):
    import torch
    sd = torch.load(path, map_location="cpu", weights_only=False)["model"]
    text = [k for k in sd if k.startswith("text_proj.")]
    width = sd["node_encoder.0.weight"].shape[1]
    if has_branch(arm):
        if not text or width != 160:
            return f"{path}: expected CodeBERT branch (text_proj present, input 160), got {len(text)} text keys, input {width}"
    else:
        if text or width != 32:
            return f"{path}: expected NO CodeBERT branch (no text_proj, input 32), got {len(text)} text keys, input {width}"
    return None

def load_model(arm, seed):
    import torch
    use_arm(arm)
    torch.set_num_threads(1)
    from utils.ablation import pinned_edge_type_mapping
    from utils.model import RelationalGNN
    ck = os.path.join(run_dir(arm, seed), "stage2", "stage2_best.pt")
    c = torch.load(ck, map_location="cpu", weights_only=False)
    cfg = c["config"]
    assert cfg["K"] == 2, f"{arm}/{seed}: K={cfg['K']}"
    kw = dict(text_dim=768, text_proj_dim=128) if has_branch(arm) else dict(text_dim=None, text_proj_dim=0)
    m = RelationalGNN(in_dim=32, hidden_dim=cfg.get("hidden_dim", 256),
                      edge_types=pinned_edge_type_mapping(), **kw)
    assert (m.text_proj is not None) == has_branch(arm)
    m.load_state_dict(c["model"], strict=True)
    m.eval()
    return m, cfg["K"]

def score(arm, model, K, names):
    import torch
    use_arm(arm)
    from utils.text_features import forward_with_text, load_text_emb
    out = []
    with torch.no_grad():
        for i, n in enumerate(names):
            g = torch.load(os.path.join(ENC, f"{n}.pt"), map_location="cpu", weights_only=False)
            if i == 0 and has_branch(arm):
                e = load_text_emb(os.environ["V7_CODEBERT_DIR"], n, g.x.shape[0])
                assert float(e.abs().sum()) > 0, "CodeBERT features are all zero"
            out.append(float(model.graph_score(forward_with_text(model, g, K=K, name=n)).item()))
    return out

def metrics(p, y, thr=THR):
    from sklearn.metrics import average_precision_score
    p, y = np.asarray(p, float), np.asarray(y, int)
    pred = (p > thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return {"f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0, "precision": pr, "recall": rc,
            "accuracy": (tp + tn) / len(y), "auc": auc(p, y), "pr_auc": float(average_precision_score(y, p)),
            "TP": tp, "FP": fp, "FN": fn, "TN": tn}

def auc(p, y):
    from scipy.stats import rankdata
    p, y = np.asarray(p, float), np.asarray(y, int)
    npos, nneg = int(y.sum()), int(len(y) - y.sum())
    r = rankdata(p)
    return float((r[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))

def f1_from_pred(pred, y):
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return 2 * pr * rc / (pr + rc) if pr + rc else 0.0

def paired_bootstrap(y, score_a, score_b):
    b = PROTO["bootstrap"]
    rng = np.random.default_rng(b["seed"])
    y = np.asarray(y, int)
    sa, sb = np.asarray(score_a, float), np.asarray(score_b, float)
    pa, pb = (sa > THR).astype(int), (sb > THR).astype(int)
    df1, dauc = [], []
    for _ in range(b["n"]):
        i = rng.integers(0, len(y), len(y))
        if b["skip_single_class"] and len(set(y[i].tolist())) < 2:
            continue
        df1.append(f1_from_pred(pa[i], y[i]) - f1_from_pred(pb[i], y[i]))
        dauc.append(auc(sa[i], y[i]) - auc(sb[i], y[i]))
    lo, hi = b["ci"]
    return {"n_resamples_used": len(df1),
            "delta_f1_ci95": [float(np.percentile(df1, lo)), float(np.percentile(df1, hi))],
            "delta_auc_ci95": [float(np.percentile(dauc, lo)), float(np.percentile(dauc, hi))]}

def write_locked(path, obj):
    if os.path.exists(path):
        raise SystemExit(f"{os.path.relpath(path, EXP)} already exists; it is written once and never overwritten")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)
    os.chmod(path, 0o444)
