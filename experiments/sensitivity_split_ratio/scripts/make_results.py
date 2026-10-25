#!/usr/bin/env python
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(STUDY))
ARMS = os.path.join(STUDY, "results", "arms")
OUT = os.path.join(STUDY, "results")

ORDER = [
    ("70_30", "70 : 30"),
    ("80_20", "80 : 20"),
    ("paper", "83.9 : 16.1"),
]
PAPER = "paper"

def load(name):
    p = os.path.join(ARMS, f"{name}.json")
    return json.load(open(p)) if os.path.exists(p) else None

shipped = load("reported_model")
assert shipped, "score the reported model first (checkpoints_final -> arms/reported_model.json)"
frozen = json.load(open(os.path.join(ROOT, "Step_4_Student", "FINAL_RESULT.json")))
for k in ("f1", "precision", "recall", "accuracy", "auc"):
    got, want = shipped["test"]["ensemble"][k], float(frozen["test"]["ensemble"][k])
    assert abs(got - want) < 1e-9, \
        f"the reported-model row does not reproduce FINAL_RESULT.json: {k} {got} vs {want}"
print(f"[check] reported model reproduces FINAL_RESULT.json exactly "
      f"(test F1 {shipped['test']['ensemble']['f1']:.4f})")

missing = [k for k, _ in ORDER if load(k) is None]
if missing:
    print(f"[incomplete] not scored yet: {', '.join(missing)}", file=sys.stderr)

rows = []
for key, disp in ORDER:
    d = load(key)
    if d is None:
        continue
    c = d["split_counts"]
    n = sum(c.values())
    assert n == 753, f"{key}: split covers {n} contracts, expected 753"
    assert abs(d["lr"] - 1e-3) < 1e-12, f"{key}: lr is {d['lr']}, expected the final 1e-3"
    r = {"arm": key, "ratio": disp, "is_paper_split": key == PAPER,
         "counts": c, "train_pct": round(100 * (c["train"] + c["val"]) / n, 1),
         "test_pct": round(100 * c["test"] / n, 1),
         "seeds": d["seeds"], "checkpoints": d["checkpoints"], "split_file": d["split_file"]}
    for part in ("val", "test"):
        e = d[part]["ensemble"]
        r[part] = {k: e[k] for k in ("precision", "recall", "f1", "accuracy", "auc",
                                     "pr_auc", "TP", "FP", "FN", "TN")}
        r[part]["n"] = d[part]["n"]
        r[part]["n_pos"] = d[part]["n_pos"]
        r[part]["ci95"] = d[part]["ci95"]
        r[part]["per_seed_f1"] = d[part]["per_seed_f1"]
        r[part]["mean_of_runs_f1"] = d[part]["mean_of_runs_f1"]
        r[part]["sd_of_runs_f1"] = d[part]["sd_of_runs_f1"]
    r["collapsed_seeds"] = [sd for sd, auc in zip(d["seeds"], d["val"]["per_seed_auc"])
                            if abs(auc - 0.5) < 1e-9]
    if r["collapsed_seeds"]:
        print(f"[collapse] {key}: seeds {r['collapsed_seeds']} predict a constant "
              f"(validation AUC 0.5); reported as-is, not replaced", file=sys.stderr)
    rows.append(r)

res = {"study": "train:test ratio sensitivity",
       "protocol": {"K": 2, "lr": 1e-3, "seeds": [201, 202, 203, 204, 205], "threshold": 0.5,
                    "ensemble": "mean probability over the five Stage-2 students",
                    "device": "CPU, 2 threads per seed",
                    "changed_setting": "SPLIT_FILE only",
                    "alternative_splits_built_by": "experiments/sensitivity_split_ratio/scripts/make_split.py",
                    "grouping_constraints": ["normalized source", "case-insensitive address",
                                             "encoded SDG representation"],
                    "comparability": "the three arms use three different test partitions; "
                                     "no paired test across arms is defined",
                    "bootstrap": {"n": 10000, "seed": 22, "unit": "contract",
                                  "type": "percentile, per arm"}},
       "reported_model": {"checkpoints": "checkpoints_final",
                          "val": shipped["val"]["ensemble"], "test": shipped["test"]["ensemble"]},
       "rows": rows, "incomplete": missing}
os.makedirs(OUT, exist_ok=True)
json.dump(res, open(os.path.join(OUT, "SPLIT_RATIO.json"), "w"), indent=1)

cols = ["ratio", "train", "val", "test", "test_P", "test_R", "test_F1", "test_AUC",
        "test_F1_CI_lo", "test_F1_CI_hi", "test_F1_mean_of_seeds", "test_F1_sd_of_seeds",
        "val_P", "val_R", "val_F1", "val_AUC"]
with open(os.path.join(OUT, "SPLIT_RATIO.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for r in rows:
        w.writerow([r["ratio"], r["counts"]["train"], r["counts"]["val"], r["counts"]["test"],
                    f"{r['test']['precision']:.4f}", f"{r['test']['recall']:.4f}",
                    f"{r['test']['f1']:.4f}", f"{r['test']['auc']:.4f}",
                    f"{r['test']['ci95']['f1'][0]:.4f}", f"{r['test']['ci95']['f1'][1]:.4f}",
                    f"{r['test']['mean_of_runs_f1']:.4f}", f"{r['test']['sd_of_runs_f1']:.4f}",
                    f"{r['val']['precision']:.4f}", f"{r['val']['recall']:.4f}",
                    f"{r['val']['f1']:.4f}", f"{r['val']['auc']:.4f}"])


print(f"[written] {os.path.relpath(OUT, ROOT)}/SPLIT_RATIO.{{json,csv}}")
for r in rows:
    print(f"  {r['ratio']:<12s} n_test {r['test']['n']:3d}  F1 {r['test']['f1']:.4f}  "
          f"P {r['test']['precision']:.4f}  R {r['test']['recall']:.4f}  AUC {r['test']['auc']:.4f}")
