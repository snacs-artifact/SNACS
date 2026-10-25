#!/usr/bin/env python
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  (verifies the frozen protocol on import)
from check_run import check  # noqa: E402

KEYS = ("f1", "precision", "recall", "auc")

def main():
    out = {"split": "val", "threshold": C.THR, "arms": {}}
    names, y = C.split_and_labels("val")
    assert len(names) == 108
    out["n"], out["n_vulnerable"] = len(names), sum(y)
    for arm in C.ARMS:
        seeds = C.slot_seeds(arm)
        for s in seeds:
            r = check((arm, s))
            assert r["status"] == "valid", f"{arm} seed {s} is not a valid run: {r}"
        per, runs = [], []
        for s in seeds:
            m, K = C.load_model(arm, s)
            sc = C.score(arm, m, K, names)
            per.append(sc)
            runs.append({"seed": s, **{k: v for k, v in C.metrics(sc, y).items()}})
        ens = [st.mean(col) for col in zip(*per)]
        out["arms"][arm] = {
            "seeds": seeds,
            "codebert_branch": C.has_branch(arm),
            "ensemble": C.metrics(ens, y),
            "runs": runs,
            "runs_mean": {k: st.mean(r[k] for r in runs) for k in KEYS},
            "runs_sd": {k: st.stdev(r[k] for r in runs) for k in KEYS},
            "ensemble_scores": dict(zip(names, ens)),
        }
        e = out["arms"][arm]["ensemble"]
        print(f"[{arm}] VAL ensemble F1 {e['f1']:.4f}  P {e['precision']:.4f}  R {e['recall']:.4f}  "
              f"AUC {e['auc']:.4f}  | runs F1 {out['arms'][arm]['runs_mean']['f1']:.4f} ± "
              f"{out['arms'][arm]['runs_sd']['f1']:.4f}", flush=True)
    C.write_locked(os.path.join(C.RES, "VALIDATION.json"), out)
    print("written -> results/VALIDATION.json")

if __name__ == "__main__":
    main()
