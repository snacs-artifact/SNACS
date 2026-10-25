#!/usr/bin/env python
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  (verifies the frozen protocol on import)

def main():
    vpath = os.path.join(C.RES, "VALIDATION.json")
    V = json.load(open(vpath))
    assert V["split"] == "val"
    names, y = C.split_and_labels("val")
    a, b = V["arms"]["nocodebert"], V["arms"]["ctrl_codebert"]
    assert list(a["ensemble_scores"]) == names == list(b["ensemble_scores"])
    sa = [a["ensemble_scores"][n] for n in names]
    sb = [b["ensemble_scores"][n] for n in names]
    d_f1 = a["ensemble"]["f1"] - b["ensemble"]["f1"]
    d_auc = a["ensemble"]["auc"] - b["ensemble"]["auc"]
    boot = C.paired_bootstrap(y, sa, sb)
    crit = {"delta_f1_val > 0": d_f1 > 0,
            "delta_f1_val_ci95_low > 0": boot["delta_f1_ci95"][0] > 0,
            "delta_auc_val >= 0": d_auc >= 0}
    assert list(crit) == C.PROTO["adopt_nocodebert_if_all"], "criteria differ from the frozen protocol"
    adopt = all(crit.values())
    D = {"decided_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
         "split_used": "val (108 contracts); no test data read",
         "protocol_sha256": {f: C.sha256(os.path.join(C.EXP, f)) for f in ("PROTOCOL.md", "protocol.json", "PROTOCOL_AMENDMENT_1.md")},
         "validation_json_sha256": C.sha256(vpath),
         "delta_f1_val": d_f1, "delta_f1_val_ci95": boot["delta_f1_ci95"],
         "delta_auc_val": d_auc, "delta_auc_val_ci95_descriptive": boot["delta_auc_ci95"],
         "bootstrap_resamples_used": boot["n_resamples_used"],
         "criteria": crit,
         "decision": "adopt_nocodebert" if adopt else "retain_codebert",
         "selected_architecture": "nocodebert" if adopt else "codebert (checkpoints_final stays final)"}
    C.write_locked(os.path.join(C.RES, "DECISION.json"), D)

    L = ["# Validation results and architecture decision", "",
         f"Validation set: {len(names)} contracts ({sum(y)} vulnerable). 5-run mean-probability ensembles, "
         f"threshold {C.THR}. No test data was read. Decided {D['decided_at']}.", "",
         "## Ensembles", "",
         "| Arm | CodeBERT branch | F1 | Precision | Recall | ROC-AUC | PR-AUC | TP/FP/FN/TN |", "|---|---|---|---|---|---|---|---|"]
    for arm, r in (("nocodebert", a), ("ctrl_codebert", b)):
        e = r["ensemble"]
        L.append(f"| {arm} | {'yes' if r['codebert_branch'] else 'no'} | {e['f1']:.4f} | {e['precision']:.4f} | "
                 f"{e['recall']:.4f} | {e['auc']:.4f} | {e['pr_auc']:.4f} | {e['TP']}/{e['FP']}/{e['FN']}/{e['TN']} |")
    L += ["", "## Individual runs", "",
          "| Arm | Seed | F1 | Precision | Recall | ROC-AUC |", "|---|---|---|---|---|---|"]
    for arm, r in (("nocodebert", a), ("ctrl_codebert", b)):
        for x in r["runs"]:
            L.append(f"| {arm} | {x['seed']} | {x['f1']:.4f} | {x['precision']:.4f} | {x['recall']:.4f} | {x['auc']:.4f} |")
        m, s = r["runs_mean"], r["runs_sd"]
        L.append(f"| {arm} | mean ± sd | {m['f1']:.4f} ± {s['f1']:.4f} | {m['precision']:.4f} ± {s['precision']:.4f} | "
                 f"{m['recall']:.4f} ± {s['recall']:.4f} | {m['auc']:.4f} ± {s['auc']:.4f} |")
    lo, hi = boot["delta_f1_ci95"]
    alo, ahi = boot["delta_auc_ci95"]
    L += ["", "## Paired comparison (nocodebert − ctrl_codebert)", "",
          f"- ΔF1 = {d_f1:+.4f}, paired-bootstrap 95% CI [{lo:+.4f}, {hi:+.4f}] "
          f"({boot['n_resamples_used']} of 10,000 resamples used)",
          f"- ΔAUC = {d_auc:+.4f} (descriptive CI [{alo:+.4f}, {ahi:+.4f}])", "",
          "## Decision (frozen rule)", ""]
    L += [f"- {k}: {'yes' if v else 'no'}" for k, v in crit.items()]
    L += ["", f"**{D['decision']}** — selected architecture: {D['selected_architecture']}", ""]
    rp = os.path.join(C.RES, "VALIDATION_REPORT.md")
    if os.path.exists(rp):
        raise SystemExit("VALIDATION_REPORT.md already exists")
    open(rp, "w").write("\n".join(L))
    os.chmod(rp, 0o444)
    print("\n".join(L))

if __name__ == "__main__":
    main()
