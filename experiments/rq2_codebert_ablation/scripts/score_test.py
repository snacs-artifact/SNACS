#!/usr/bin/env python
import json
import math
import os
import stat
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  (verifies the frozen protocol on import)
from check_run import check  # noqa: E402

def mcnemar(y, pa, pb):
    ca = [int(p == t) for p, t in zip(pa, y)]
    cb = [int(p == t) for p, t in zip(pb, y)]
    b = sum(1 for u, v in zip(ca, cb) if u and not v)
    c = sum(1 for u, v in zip(ca, cb) if v and not u)
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)

def main():
    dpath, vpath = os.path.join(C.RES, "DECISION.json"), os.path.join(C.RES, "VALIDATION.json")
    tpath = os.path.join(C.RES, "TEST_RESULT.json")
    if os.path.exists(tpath):
        raise SystemExit("TEST_RESULT.json exists: the test set is scored once only")
    if not os.path.exists(dpath) or os.stat(dpath).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise SystemExit("no locked results/DECISION.json: run decide.py first")
    D = json.load(open(dpath))
    for f, h in D["protocol_sha256"].items():
        assert C.sha256(os.path.join(C.EXP, f)) == h, f"{f} changed after the decision"
    assert C.sha256(vpath) == D["validation_json_sha256"], "VALIDATION.json changed after the decision"

    ref = os.path.join(C.EXP, "reference", "vfinal_FINAL_RESULT.json")
    manifest = {l.split("  ", 1)[1].strip(): l.split("  ", 1)[0]
                for l in open(os.path.join(C.EXP, "reference", "vfinal_work_MANIFEST.sha256")) if l.strip()}
    assert C.sha256(ref) == manifest["vfinal_work/Step_3_GraphLearning/FINAL_RESULT.json"], "reference result changed"
    R = json.load(open(ref))

    names, y = C.split_and_labels("test")
    assert len(names) == 121 and list(R["test"]["scores"]) == names
    full_scores = [R["test"]["scores"][n] for n in names]
    full = C.metrics(full_scores, y)
    assert abs(full["f1"] - C.PROTO["test_full_framework_reference"]["f1"]) < 1e-12

    out = {"split": "test", "n": 121, "n_vulnerable": sum(y), "decision": D["decision"],
           "selected_architecture": D["selected_architecture"], "full_framework_reference": full, "arms": {}}
    ens_scores = {}
    for arm in C.ARMS:
        seeds = C.slot_seeds(arm)
        assert seeds == json.load(open(vpath))["arms"][arm]["seeds"], f"{arm}: seeds differ from the validation run"
        for s in seeds:
            assert check((arm, s))["status"] == "valid"
        per, runs = [], []
        for s in seeds:
            m, K = C.load_model(arm, s)
            sc = C.score(arm, m, K, names)
            per.append(sc)
            runs.append({"seed": s, **C.metrics(sc, y)})
        ens = [st.mean(col) for col in zip(*per)]
        ens_scores[arm] = ens
        out["arms"][arm] = {"seeds": seeds, "ensemble": C.metrics(ens, y), "runs": runs,
                            "runs_mean": {k: st.mean(r[k] for r in runs) for k in ("f1", "precision", "recall", "auc")},
                            "runs_sd": {k: st.stdev(r[k] for r in runs) for k in ("f1", "precision", "recall", "auc")},
                            "ensemble_scores": dict(zip(names, ens))}

    def compare(sa, sb):
        ma, mb = C.metrics(sa, y), C.metrics(sb, y)
        bt = C.paired_bootstrap(y, sa, sb)
        pa = [int(s > C.THR) for s in sa]
        pb = [int(s > C.THR) for s in sb]
        return {"delta_f1": ma["f1"] - mb["f1"], "delta_f1_ci95": bt["delta_f1_ci95"],
                "delta_auc": ma["auc"] - mb["auc"], "delta_auc_ci95": bt["delta_auc_ci95"],
                "mcnemar_p": mcnemar(y, pa, pb)}

    out["comparisons"] = {
        "nocodebert_vs_full_framework": compare(ens_scores["nocodebert"], full_scores),
        "nocodebert_vs_ctrl_codebert": compare(ens_scores["nocodebert"], ens_scores["ctrl_codebert"]),
        "ctrl_codebert_vs_full_framework": compare(ens_scores["ctrl_codebert"], full_scores),
    }
    sel = out["arms"]["nocodebert"]["ensemble"] if D["decision"] == "adopt_nocodebert" else full
    out["selected_architecture_test"] = sel
    C.write_locked(tpath, out)

    a, c = out["arms"]["nocodebert"], out["arms"]["ctrl_codebert"]
    L = ["# Test results (scored once, after the locked validation decision)", "",
         f"Test set: 121 contracts ({sum(y)} vulnerable). 5-run ensembles, threshold {C.THR}. "
         f"Decision taken on validation beforehand: **{D['decision']}**.", "",
         "| Model | F1 | Precision | Recall | ROC-AUC | PR-AUC | TP/FP/FN/TN |", "|---|---|---|---|---|---|---|"]
    for label, e in (("Full framework (vfinal_work, frozen)", full), ("nocodebert (retrained)", a["ensemble"]),
                     ("ctrl_codebert (retrained control)", c["ensemble"])):
        L.append(f"| {label} | {e['f1']:.4f} | {e['precision']:.4f} | {e['recall']:.4f} | {e['auc']:.4f} | "
                 f"{e['pr_auc']:.4f} | {e['TP']}/{e['FP']}/{e['FN']}/{e['TN']} |")
    L += ["", "| Arm | runs F1 mean ± sd | runs AUC mean ± sd |", "|---|---|---|"]
    for arm, r in (("nocodebert", a), ("ctrl_codebert", c)):
        L.append(f"| {arm} | {r['runs_mean']['f1']:.4f} ± {r['runs_sd']['f1']:.4f} | "
                 f"{r['runs_mean']['auc']:.4f} ± {r['runs_sd']['auc']:.4f} |")
    L += ["", "| Comparison | ΔF1 | 95% CI | ΔAUC | McNemar p |", "|---|---|---|---|---|"]
    for k, v in out["comparisons"].items():
        L.append(f"| {k} | {v['delta_f1']:+.4f} | [{v['delta_f1_ci95'][0]:+.3f}, {v['delta_f1_ci95'][1]:+.3f}] | "
                 f"{v['delta_auc']:+.4f} | {v['mcnemar_p']:.3f} |")
    L += ["", f"Selected architecture on test: F1 {sel['f1']:.4f}, P {sel['precision']:.4f}, "
          f"R {sel['recall']:.4f}, AUC {sel['auc']:.4f}.", ""]
    rp = os.path.join(C.RES, "TEST_REPORT.md")
    open(rp, "w").write("\n".join(L)); os.chmod(rp, 0o444)

    v = out["comparisons"]["nocodebert_vs_full_framework"]
    e = a["ensemble"]
    num = lambda x, d: "0" if abs(x) < 0.5 * 10 ** -d else f"{x:+.{d}f}"
    dd, ci = num(v["delta_f1"], 4), f"[{num(v['delta_f1_ci95'][0], 3)}, {num(v['delta_f1_ci95'][1], 3)}]"
    if v["delta_f1_ci95"][0] > 0 or v["delta_f1_ci95"][1] < 0:
        dd, ci = f"\\mathbf{{{dd}}}", f"\\mathbf{{{ci}}}"
    row = (f"w/o CodeBERT features & {e['precision']:.4f} & {e['recall']:.4f} & {e['f1']:.4f} & {e['auc']:.4f} & "
           f"${dd}$ & ${ci}$ \\\\\n")
    tp = os.path.join(C.RES, "ABLATION_ROW_nocodebert.tex")
    open(tp, "w").write("% Table VII-style row; dF1 and CI against the full framework (vfinal_work)\n" + row)
    os.chmod(tp, 0o444)
    print("\n".join(L))
    print(row)

if __name__ == "__main__":
    main()
