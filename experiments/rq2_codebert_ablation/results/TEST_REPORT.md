# Test results (scored once, after the locked validation decision)

Test set: 121 contracts (65 vulnerable). 5-run ensembles, threshold 0.5. Decision taken on validation beforehand: **retain_codebert**.

| Model | F1 | Precision | Recall | ROC-AUC | PR-AUC | TP/FP/FN/TN |
|---|---|---|---|---|---|---|
| Full framework (vfinal_work, frozen) | 0.8550 | 0.8485 | 0.8615 | 0.9209 | 0.9394 | 56/10/9/46 |
| nocodebert (retrained) | 0.8527 | 0.8594 | 0.8462 | 0.9181 | 0.9414 | 55/9/10/47 |
| ctrl_codebert (retrained control) | 0.8594 | 0.8730 | 0.8462 | 0.9170 | 0.9365 | 55/8/10/48 |

| Arm | runs F1 mean ± sd | runs AUC mean ± sd |
|---|---|---|
| nocodebert | 0.8357 ± 0.0116 | 0.9043 ± 0.0090 |
| ctrl_codebert | 0.8229 ± 0.0161 | 0.9075 ± 0.0143 |

| Comparison | ΔF1 | 95% CI | ΔAUC | McNemar p |
|---|---|---|---|---|
| nocodebert_vs_full_framework | -0.0022 | [-0.032, +0.026] | -0.0027 | 1.000 |
| nocodebert_vs_ctrl_codebert | -0.0067 | [-0.045, +0.031] | +0.0011 | 1.000 |
| ctrl_codebert_vs_full_framework | +0.0044 | [-0.036, +0.044] | -0.0038 | 1.000 |

Selected architecture on test: F1 0.8550, P 0.8485, R 0.8615, AUC 0.9209.
