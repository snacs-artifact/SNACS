#!/usr/bin/env python
import csv
import hashlib
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
T78 = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(T78))
RES = os.path.join(T78, "results")
SEEDS = [201, 202, 203, 204, 205]
THR = 0.5
BOOT_N, BOOT_SEED = 10000, 22

ARMS = {
    "nocontains": ("VIII", "w/o `contains`", "ctrl_full", "", "", "contains"),
    "noseq": ("VIII", "w/o `seq`", "ctrl_full", "", "", "seq"),
    "nocf": ("VIII", "w/o `cf`", "ctrl_full", "", "", "cf"),
    "nodd": ("VIII", "w/o `dd`", "ctrl_full", "", "", "dd"),
    "nogd": ("VIII", "w/o `gd`", "ctrl_full", "", "", "gd"),
    "nosd": ("VIII", "w/o `sd`", "ctrl_full", "", "", "sd"),
    "taint_only": ("IX", "Taint-only teacher, no c_v",
                   "ctrl_from_s0", "TAINT_ONLY_TEACHER=1", "", ""),
    "wo_teachersup": ("IX", "w/o Stage-1 teacher supervision",
                      "ctrl_from_s0", "ABLATE_LOSS=graph_teacher,node,traj", "", ""),
    "wo_graph_teacher": ("IX", "w/o graph-level teacher loss",
                         "ctrl_from_s0", "ABLATE_LOSS=graph_teacher", "", ""),
    "wo_node": ("IX", "w/o node alignment L_node",
                "ctrl_from_s0", "ABLATE_LOSS=node", "", ""),
    "wo_traj": ("IX", "w/o trajectory alignment L_traj",
                "ctrl_from_s0", "ABLATE_LOSS=traj", "", ""),
    "wo_maskedstruct": ("IX", "w/o masked-structure objectives",
                        "ctrl_from_s1", "", "ABLATE_LOSS=node_rec,link", ""),
}
CONTROLS = {
    "ctrl_full": ("Retrained full framework (all stages)", 0),
    "ctrl_from_s0": ("Retrained full framework (stages 1-2 from shipped stage 0)", 1),
    "ctrl_from_s1": ("Retrained full framework (stage 2 from shipped stage 1)", 2),
}
START = {**{a: 0 for a in ARMS if ARMS[a][0] == "VIII"}, "taint_only": 1, "wo_teachersup": 1,
         "wo_graph_teacher": 1, "wo_node": 1, "wo_traj": 1, "wo_maskedstruct": 2,
         **{c: s for c, (_, s) in CONTROLS.items()}}

def prf(y, pred):
    y, pred = np.asarray(y), np.asarray(pred)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0

def paired_bootstrap(y, pa, pb):
    rng = np.random.default_rng(BOOT_SEED)
    y, pa, pb = np.asarray(y), np.asarray(pa), np.asarray(pb)
    d = []
    for _ in range(BOOT_N):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i].tolist())) < 2:
            continue
        d.append(prf(y[i], pa[i]) - prf(y[i], pb[i]))
    d = np.asarray(d)
    return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]

def mcnemar(y, pa, pb):
    ca = [int(p == t) for p, t in zip(pa, y)]
    cb = [int(p == t) for p, t in zip(pb, y)]
    b = sum(1 for u, v in zip(ca, cb) if u == 1 and v == 0)
    c = sum(1 for u, v in zip(ca, cb) if u == 0 and v == 1)
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p": 1.0}
    k = min(b, c)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"b": b, "c": c, "p": p}

def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, (len(ps) - rank) * ps[i])
        adj[i] = min(1.0, run)
    return adj

def expected_describe(drop, abl, taint):
    d = f"['{drop}']" if drop else "none"
    a = "[" + ", ".join(f"'{t}'" for t in abl.split(",")) + "]" if abl else "none"
    return f"DROP_RELATIONS={d}  ABLATE_LOSS={a}  TAINT_ONLY_TEACHER={1 if taint else 0}"

def seed_record(arm):
    p = os.path.join(T78, "runs", arm, "SEEDS.json")
    if os.path.exists(p):
        return json.load(open(p))
    return {"slots": {str(s): s for s in SEEDS}, "replacements": []}

def arm_seeds(arm):
    slots = seed_record(arm)["slots"]
    return [int(slots[k]) for k in sorted(slots)]

def audit(arm, scored=None):
    problems = []
    if scored is not None:
        drop = ARMS[arm][5] if arm in ARMS else ""
        for part in ("val", "test"):
            cnt = scored[part]["edges_per_relation"]
            for rel, c in cnt.items():
                if (rel == drop) != (c == 0):
                    problems.append(f"scored {part} graphs have {c} {rel} edges (dropped: {drop or 'none'})")
    if arm in ARMS:
        _, _, _, s1, s2, drop = ARMS[arm]
    else:
        s1 = s2 = drop = ""
    start = START[arm]
    for s in arm_seeds(arm):
        run = os.path.join(T78, "runs", arm, f"final_init{s}")
        logs = os.path.join(T78, "logs", arm, f"s{s}")
        need = [os.path.join(run, "ARM.json"), os.path.join(run, "stage2", "stage2_best.pt")] + \
               [os.path.join(logs, f"stage{k}.log") for k in range(start, 3)]
        missing = [p for p in need if not os.path.exists(p)]
        if missing:
            problems.append(f"s{s}: run incomplete ({os.path.relpath(missing[0], T78)} missing)")
            continue
        rec = json.load(open(os.path.join(run, "ARM.json")))
        if rec["start_stage"] != start:
            problems.append(f"s{s}: start_stage {rec['start_stage']} != {start}")
        if rec.get("env", {}).get("DROP_RELATIONS", "") != drop:
            problems.append(f"s{s}: ARM.json DROP_RELATIONS={rec.get('env')} != {drop!r}")
        for stage, env in ((1, s1), (2, s2)):
            if stage < start:
                continue
            txt = open(os.path.join(logs, f"stage{stage}.log"), errors="replace").read()
            abl = env.split("=", 1)[1] if env.startswith("ABLATE_LOSS=") else ""
            want = expected_describe(drop, abl, env == "TAINT_ONLY_TEACHER=1")
            m = re.search(r"^ABLATION: (.*)$", txt, re.M)
            if not m or m.group(1).strip() != want:
                problems.append(f"s{s} stage{stage}: ABLATION line {m.group(1).strip() if m else None!r} != {want!r}")
            if "TEST EVALUATION" not in txt:
                problems.append(f"s{s} stage{stage}: log incomplete")
        if start == 0:
            txt = open(os.path.join(logs, "stage0.log"), errors="replace").read()
            if "TEST EVALUATION" not in txt:
                problems.append(f"s{s} stage0: log incomplete")
        for stage in range(start):                     # inherited stages
            f = os.path.join(run, f"stage{stage}", f"stage{stage}_best.pt")
            ship = os.path.join(ROOT, "checkpoints_final", f"final_init{s}", f"stage{stage}", f"stage{stage}_best.pt")
            h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
            if h(f) != h(ship):
                problems.append(f"s{s}: inherited stage{stage} differs from the shipped checkpoint")
    return problems

def load(arm):
    p = os.path.join(RES, "arms", f"{arm}.json")
    return json.load(open(p)) if os.path.exists(p) else None

SCORES_ONLY = "--scores-only" in sys.argv

def main():
    full = load("full_shipped")
    ship = json.load(open(os.path.join(ROOT, "Step_4_Student", "FINAL_RESULT.json")))
    assert full is not None, "score the shipped model first: score_arm.py --arm full_shipped"
    for part in ("val", "test"):
        assert full[part]["scores"] == ship[part]["scores"], f"re-scored shipped {part} scores differ from FINAL_RESULT.json"
        assert full[part]["ensemble"] == ship[part]["ensemble"], f"re-scored shipped {part} metrics differ"
    names = list(full["test"]["scores"])
    lab = {}
    for line in open(os.path.join(ROOT, "Dataset", "FINAL_CLEAN_DATASET", "labels.csv")):
        q = line.strip().split(",")
        if len(q) >= 2 and q[1] in ("0", "1"):
            lab[q[0]] = int(q[1])
    y = [lab[n] for n in names]
    pred = lambda sc: [int(sc[n] > THR) for n in names]
    full_pred = pred(full["test"]["scores"])
    full_f1 = full["test"]["ensemble"]["f1"]
    assert abs(full_f1 - 0.8549618320610687) < 1e-12, full_f1

    rows, status = {}, {}
    for arm in list(ARMS) + list(CONTROLS):
        r = load(arm)
        if r is None:
            status[arm] = "PENDING"
            continue
        expected = arm_seeds(arm)
        probs = [] if SCORES_ONLY else audit(arm, r if r["seeds"] == expected else None)
        if r["seeds"] != expected:
            probs.append(f"scored on seeds {r['seeds']}, expected {expected} (runs/{arm}/SEEDS.json)")
        for s, auc in zip(r["seeds"], r["val"]["per_seed_auc"]):
            if abs(auc - 0.5) < 1e-12:
                probs.append(f"seed {s} is a training collapse (validation AUC 0.5): "
                             f"run apply_validity_rule.sh {arm} <slot>, then re-score")
        e = r["test"]["ensemble"]
        ap = pred(r["test"]["scores"])
        assert list(r["test"]["scores"]) == names, f"{arm}: test contracts differ from the reference"
        assert abs(prf(y, ap) - e["f1"]) < 1e-12, f"{arm}: stored ensemble F1 disagrees with its scores"
        row = {"arm": arm, "audit_problems": probs,
               "test": {k: e[k] for k in ("precision", "recall", "f1", "accuracy", "auc", "pr_auc", "TP", "FP", "FN", "TN")},
               "val": {k: r["val"]["ensemble"][k] for k in ("precision", "recall", "f1", "auc")},
               "per_seed_test_f1": r["test"]["per_seed_f1"],
               "mean_of_runs_test_f1": r["test"]["mean_of_runs_f1"], "sd_of_runs_test_f1": r["test"]["sd_of_runs_f1"],
               "per_seed_val_auc": r["val"]["per_seed_auc"],
               "delta_f1": e["f1"] - full_f1,
               "delta_f1_ci95": paired_bootstrap(y, ap, full_pred),
               "mcnemar_vs_full": mcnemar(y, ap, full_pred),
               "seeds": r["seeds"], "seed_replacements": seed_record(arm)["replacements"],
               "_pred": ap}
        rows[arm] = row
        status[arm] = "DONE" if not probs else "AUDIT FAILED"

    for arm, row in rows.items():                     # against the matching retrained control
        ctrl = ARMS[arm][2] if arm in ARMS else None
        if ctrl and ctrl in rows:
            row["control"] = ctrl
            row["delta_f1_vs_control"] = row["test"]["f1"] - rows[ctrl]["test"]["f1"]
            row["delta_f1_vs_control_ci95"] = paired_bootstrap(y, row["_pred"], rows[ctrl]["_pred"])
    for table in ("VIII", "IX"):
        done = [a for a in ARMS if ARMS[a][0] == table and status.get(a) == "DONE"]
        for a, p in zip(done, holm([rows[a]["mcnemar_vs_full"]["p"] for a in done])):
            rows[a]["mcnemar_holm_p"] = p

    os.makedirs(RES, exist_ok=True)
    fe = full["test"]["ensemble"]
    bad = {a: rows[a]["audit_problems"] for a in rows if rows[a]["audit_problems"]}
    out = {"reference": {"arm": "full_shipped", "checkpoints": "checkpoints_final", "test": fe,
                         "val": full["val"]["ensemble"]},
           "n_test": len(y), "threshold": THR, "bootstrap": {"n": BOOT_N, "seed": BOOT_SEED},
           "status": status, "audit_problems": bad,
           "arms": {a: {k: v for k, v in r.items() if not k.startswith("_")} for a, r in rows.items()}}
    json.dump(out, open(os.path.join(RES, "ABLATION_RESULTS.json"), "w"), indent=1)

    with open(os.path.join(RES, "ABLATION_RESULTS.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["table", "arm", "status", "precision", "recall", "f1", "accuracy", "auc", "pr_auc",
                    "TP", "FP", "FN", "TN", "delta_f1", "ci_lo", "ci_hi", "mcnemar_p", "holm_p",
                    "control", "delta_f1_vs_control", "ctrl_ci_lo", "ctrl_ci_hi",
                    "mean_of_runs_f1", "sd_of_runs_f1", "val_f1", "val_auc"])
        w.writerow(["ref", "full_shipped", "DONE", fe["precision"], fe["recall"], fe["f1"], fe["accuracy"],
                    fe["auc"], fe["pr_auc"], fe["TP"], fe["FP"], fe["FN"], fe["TN"], 0, "", "", "", "", "", "", "", "",
                    full["test"]["mean_of_runs_f1"], full["test"]["sd_of_runs_f1"],
                    full["val"]["ensemble"]["f1"], full["val"]["ensemble"]["auc"]])
        for a in list(ARMS) + list(CONTROLS):
            if a not in rows:
                w.writerow([ARMS[a][0] if a in ARMS else "control", a, status[a]] + [""] * 23)
                continue
            r, t = rows[a], rows[a]["test"]
            w.writerow([ARMS[a][0] if a in ARMS else "control", a, status[a], t["precision"], t["recall"], t["f1"],
                        t["accuracy"], t["auc"], t["pr_auc"], t["TP"], t["FP"], t["FN"], t["TN"],
                        r["delta_f1"], *r["delta_f1_ci95"], r["mcnemar_vs_full"]["p"], r.get("mcnemar_holm_p", ""),
                        r.get("control", ""), r.get("delta_f1_vs_control", ""),
                        *(r.get("delta_f1_vs_control_ci95") or ["", ""]),
                        r["mean_of_runs_test_f1"], r["sd_of_runs_test_f1"], r["val"]["f1"], r["val"]["auc"]])


    n_done = sum(v == "DONE" for v in status.values())
    print(f"{n_done}/{len(status)} arms done; pending: {[a for a, v in status.items() if v == 'PENDING']}")
    if bad:
        print("AUDIT PROBLEMS:", json.dumps(bad, indent=1))

if __name__ == "__main__":
    main()
