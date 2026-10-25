#!/usr/bin/env python
import csv
import json
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(STUDY))            # SNACS
D = os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET")
RES = os.path.join(STUDY, "results")

sp = json.load(open(f"{D}/split.json"))
TEST = sp["test"]
assert len(TEST) == 121
lab = {}
for line in open(f"{D}/labels.csv"):
    p = line.strip().split(",")
    if len(p) >= 2 and p[1] in ("0", "1"):
        lab[p[0]] = int(p[1])

def src(n):
    for d in ("vulnerable", "non_vulnerable"):
        p = f"{D}/{d}/{n}.sol"
        if os.path.exists(p):
            return open(p, encoding="utf8", errors="replace").read()
    raise FileNotFoundError(n)

PATTERNS = [
    ("Modifier-based guard",    lambda t: re.search(r'\bmodifier\s+only\w*', t)),
    ("Inline sender check",     lambda t: re.search(r'require\s*\([^)]*msg\.sender\s*==', t)),
    ("Ownership transfer",      lambda t: re.search(r'function\s+(transferOwnership|changeOwner|setOwner)', t)),
    ("tx.origin authorisation", lambda t: re.search(r'tx\.origin', t)),
    ("selfdestruct present",    lambda t: re.search(r'selfdestruct|suicide', t)),
    ("delegatecall present",    lambda t: re.search(r'delegatecall', t)),
    ("Role-based (RBAC)",       lambda t: re.search(r'hasRole|AccessControl|_ROLE\b', t)),
]

def metrics(names, pred, thr=0.5):
    y = [lab[n] for n in names]; s = [pred[n] for n in names]
    tp = sum(1 for a, b in zip(s, y) if a > thr and b == 1); fp = sum(1 for a, b in zip(s, y) if a > thr and b == 0)
    fn = sum(1 for a, b in zip(s, y) if a <= thr and b == 1); tn = sum(1 for a, b in zip(s, y) if a <= thr and b == 0)
    pr = tp / (tp + fp) if tp + fp else float('nan'); rc = tp / (tp + fn) if tp + fn else float('nan')
    f1 = 2 * pr * rc / (pr + rc) if (pr == pr and rc == rc and pr + rc) else float('nan')
    P = [a for a, b in zip(s, y) if b == 1]; N = [a for a, b in zip(s, y) if b == 0]
    auc = sum((i > j) + 0.5 * (i == j) for i in P for j in N) / (len(P) * len(N)) if P and N else float('nan')
    return dict(n=len(names), v=sum(y), s=len(y) - sum(y), P=pr, R=rc, f1=f1, acc=(tp + tn) / len(y), auc=auc,
                TP=tp, FP=fp, FN=fn, TN=tn)

def boot(names, pred, k=2000):
    random.seed(22); out = []
    for _ in range(k):
        b = [random.choice(names) for _ in names]
        if len({lab[n] for n in b}) < 2:
            continue
        r = metrics(b, pred)
        if r["f1"] == r["f1"]:
            out.append(r["f1"])
    out.sort()
    return (out[int(.025 * len(out))], out[int(.975 * len(out))]) if out else (float('nan'),) * 2

def nan2none(x):
    return None if isinstance(x, float) and x != x else x

txt = {n: src(n) for n in TEST}
member = {nm: [n for n in TEST if f(txt[n])] for nm, f in PATTERNS}
no_pattern = [n for n in TEST if not any(f(txt[n]) for _, f in PATTERNS)]

def analyse(pred):
    rows = {}
    for nm, _ in PATTERNS:
        names = member[nm]
        r = metrics(names, pred); lo, hi = boot(names, pred)
        small = r["n"] < 30 or r["v"] < 8 or r["s"] < 8
        rows[nm] = {**{k: nan2none(v) for k, v in r.items()}, "ci": [nan2none(lo), nan2none(hi)],
                    "underpowered": small}
    return rows

scored = json.load(open(f"{RES}/reported_model_test_scores.json"))
shipped = json.load(open(os.path.join(ROOT, "Step_4_Student", "FINAL_RESULT.json")))
pred = scored["test"]["scores"]
assert scored["test"]["K"] == 2 and scored["checkpoints"] == "checkpoints_final"
assert set(pred) == set(TEST)
assert pred == shipped["test"]["scores"], "re-scored checkpoints differ from FINAL_RESULT.json"
overall = metrics(TEST, pred)
assert (overall["TP"], overall["FP"], overall["FN"], overall["TN"]) == (56, 10, 9, 46)
assert round(overall["f1"], 4) == 0.8550 and round(overall["auc"], 4) == 0.9209
print("check OK: scores equal FINAL_RESULT.json; all 121 contracts give F1 0.8550, AUC 0.9209")

final = analyse(pred)
lo, hi = boot(TEST, pred)
out = {
    "model": "SNACS checkpoints_final, K = 2, 5-seed mean-probability ensemble, threshold 0.5",
    "test_contracts": len(TEST),
    "all_contracts": {**overall, "ci": [lo, hi]},
    "patterns": final,
    "no_pattern_matched": {**{k: nan2none(v) for k, v in metrics(no_pattern, pred).items()}},
    "pattern_rules": {nm: next(c for c in f.__code__.co_consts if isinstance(c, str)) for nm, f in PATTERNS},
    "bootstrap": "percentile, 2000 resamples, random.seed(22), resamples with one class skipped",
    "underpowered_rule": "n < 30 or fewer than 8 contracts in either class",
}
json.dump(out, open(f"{RES}/PATTERNS.json", "w"), indent=1)

with open(f"{RES}/pattern_membership.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["contract", "label", "score_k2", "predicted_k2"] + [nm for nm, _ in PATTERNS])
    for n in TEST:
        w.writerow([n, lab[n], f"{pred[n]:.6f}", int(pred[n] > 0.5)] + [int(n in member[nm]) for nm, _ in PATTERNS])

with open(f"{RES}/PATTERNS.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["pattern", "n", "vulnerable", "safe", "precision", "recall", "f1", "accuracy", "auc",
                "TP", "FP", "FN", "TN", "f1_ci_lo", "f1_ci_hi", "underpowered"])
    for nm, _ in PATTERNS:
        r = final[nm]
        w.writerow([nm, r["n"], r["v"], r["s"], r["P"], r["R"], r["f1"], r["acc"], r["auc"],
                    r["TP"], r["FP"], r["FN"], r["TN"], r["ci"][0], r["ci"][1], r["underpowered"]])


print("written ->", RES)
