#!/usr/bin/env python
import csv
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(STUDY))
ARMS = os.path.join(STUDY, "results", "arms")
OUT = os.path.join(STUDY, "results")

ORDER = [
    ("lr1e-4", "1e-4", 1e-4),
    ("lr5e-4", "5e-4", 5e-4),
    ("lr1e-3", "1e-3", 1e-3),
    ("lr5e-3", "5e-3", 5e-3),
    ("lr1e-2", "1e-2", 1e-2),
]
ADOPTED = "lr1e-3"
BOOT_N, BOOT_SEED = 10000, 22

def load(name):
    p = os.path.join(ARMS, f"{name}.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p))

def f1_at(scores, y, idx, thr=0.5):
    tp = sum(1 for i in idx if scores[i] > thr and y[i] == 1)
    fp = sum(1 for i in idx if scores[i] > thr and y[i] == 0)
    fn = sum(1 for i in idx if scores[i] <= thr and y[i] == 1)
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0

def paired_delta_ci(arm, ref, labels, part="test"):
    names = sorted(arm[part]["scores"])
    assert names == sorted(ref[part]["scores"]), "arms were scored on different contracts"
    a = [arm[part]["scores"][n] for n in names]
    b = [ref[part]["scores"][n] for n in names]
    y = [labels[n] for n in names]
    rng = random.Random(BOOT_SEED)
    m = len(names)
    draws = []
    for _ in range(BOOT_N):
        idx = [rng.randrange(m) for _ in range(m)]
        draws.append(f1_at(a, y, idx) - f1_at(b, y, idx))
    draws.sort()
    return (f1_at(a, y, range(m)) - f1_at(b, y, range(m)),
            [draws[int(0.025 * BOOT_N)], draws[int(0.975 * BOOT_N) - 1]])

labels = {}
for line in open(os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET", "labels.csv")):
    p = line.strip().split(",")
    if len(p) >= 2 and p[1] in ("0", "1"):
        labels[p[0]] = int(p[1])

shipped = load("reported_model")
assert shipped, "score the reported model first (checkpoints_final -> arms/reported_model.json)"
frozen = json.load(open(os.path.join(ROOT, "Step_4_Student", "FINAL_RESULT.json")))

for k in ("f1", "precision", "recall", "accuracy", "auc"):
    got, want = shipped["test"]["ensemble"][k], float(frozen["test"]["ensemble"][k])
    assert abs(got - want) < 1e-9, \
        f"the reported-model row does not reproduce FINAL_RESULT.json: {k} {got} vs {want}"
print(f"[check] reported model reproduces FINAL_RESULT.json exactly "
      f"(test F1 {shipped['test']['ensemble']['f1']:.4f})")

missing = [k for k, _, _ in ORDER if load(k) is None]
if missing:
    print(f"[incomplete] not scored yet: {', '.join(missing)}", file=sys.stderr)

rows = []
ref = load(ADOPTED)
for key, disp, lr in ORDER:
    d = load(key)
    if d is None:
        continue
    assert abs(d["lr"] - lr) < 1e-12, f"{key}: checkpoints carry lr={d['lr']}, expected {lr}"
    r = {"arm": key, "lr": disp, "lr_value": lr, "adopted": key == ADOPTED,
         "seeds": d["seeds"], "checkpoints": d["checkpoints"]}
    for part in ("val", "test"):
        e = d[part]["ensemble"]
        r[part] = {k: e[k] for k in ("precision", "recall", "f1", "accuracy", "auc",
                                     "pr_auc", "TP", "FP", "FN", "TN")}
        r[part]["ci95"] = d[part]["ci95"]
        r[part]["per_seed_f1"] = d[part]["per_seed_f1"]
        r[part]["mean_of_runs_f1"] = d[part]["mean_of_runs_f1"]
        r[part]["sd_of_runs_f1"] = d[part]["sd_of_runs_f1"]
    r["collapsed_seeds"] = [sd for sd, auc in zip(d["seeds"], d["val"]["per_seed_auc"])
                            if abs(auc - 0.5) < 1e-9]
    if r["collapsed_seeds"]:
        print(f"[collapse] {key}: seeds {r['collapsed_seeds']} predict a constant "
              f"(validation AUC 0.5). Reported as-is, not replaced: at a learning rate "
              f"this far from the adopted one, a run that will not train is a property "
              f"of the learning rate, not a bad draw.", file=sys.stderr)
    if ref is not None and key != ADOPTED:
        dv, civ = paired_delta_ci(d, ref, labels, part="val")
        r["delta_f1_vs_adopted_val"] = dv
        r["delta_f1_vs_adopted_val_ci95"] = civ
        dl, ci = paired_delta_ci(d, ref, labels)
        r["delta_f1_vs_adopted"] = dl
        r["delta_f1_vs_adopted_ci95"] = ci
        r["val_separated_from_adopted"] = civ[0] > 0 or civ[1] < 0
    rows.append(r)

best_val = max(rows, key=lambda r: r["val"]["f1"])["arm"] if rows else None
res = {"study": "learning-rate sweep",
       "protocol": {"K": 2, "split": "Dataset/FINAL_CLEAN_DATASET/split.json (524/108/121, frozen)",
                    "seeds": [201, 202, 203, 204, 205], "threshold": 0.5,
                    "ensemble": "mean probability over the five Stage-2 students",
                    "device": "CPU, 2 threads per seed",
                    "changed_setting": "lr in config/best_stage0_config.json; "
                                       "stages 1 and 2 inherit it",
                    "selection": "validation; the test column is reported, not selected on",
                    "bootstrap": {"n": BOOT_N, "seed": BOOT_SEED, "unit": "contract"}},
       "reported_model": {"checkpoints": "checkpoints_final", "lr": 1e-3,
                          "val": shipped["val"]["ensemble"], "test": shipped["test"]["ensemble"]},
       "adopted_arm": ADOPTED, "best_val_f1_arm": best_val, "rows": rows,
       "incomplete": missing}
os.makedirs(OUT, exist_ok=True)
json.dump(res, open(os.path.join(OUT, "LR_SWEEP.json"), "w"), indent=1)

cols = ["lr", "adopted", "val_P", "val_R", "val_F1", "val_AUC",
        "test_P", "test_R", "test_F1", "test_AUC", "test_F1_CI_lo", "test_F1_CI_hi",
        "test_dF1_vs_adopted", "test_dF1_CI_lo", "test_dF1_CI_hi",
        "test_F1_mean_of_seeds", "test_F1_sd_of_seeds"]
with open(os.path.join(OUT, "LR_SWEEP.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for r in rows:
        d = r.get("delta_f1_vs_adopted")
        ci = r.get("delta_f1_vs_adopted_ci95", [None, None])
        w.writerow([r["lr"], "yes" if r["adopted"] else "",
                    f"{r['val']['precision']:.4f}", f"{r['val']['recall']:.4f}",
                    f"{r['val']['f1']:.4f}", f"{r['val']['auc']:.4f}",
                    f"{r['test']['precision']:.4f}", f"{r['test']['recall']:.4f}",
                    f"{r['test']['f1']:.4f}", f"{r['test']['auc']:.4f}",
                    f"{r['test']['ci95']['f1'][0]:.4f}", f"{r['test']['ci95']['f1'][1]:.4f}",
                    "" if d is None else f"{d:+.4f}",
                    "" if ci[0] is None else f"{ci[0]:+.4f}",
                    "" if ci[1] is None else f"{ci[1]:+.4f}",
                    f"{r['test']['mean_of_runs_f1']:.4f}", f"{r['test']['sd_of_runs_f1']:.4f}"])


print(f"[written] {os.path.relpath(OUT, ROOT)}/LR_SWEEP.{{json,csv}}")
for r in rows:
    print(f"  lr {r['lr']:<5s} val F1 {r['val']['f1']:.4f}  test F1 {r['test']['f1']:.4f} "
          f"(P {r['test']['precision']:.4f} R {r['test']['recall']:.4f})"
          + ("   <- adopted" if r["adopted"] else ""))
