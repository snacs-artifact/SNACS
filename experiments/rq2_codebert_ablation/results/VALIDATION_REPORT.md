# Validation results and architecture decision

Validation set: 108 contracts (57 vulnerable). 5-run mean-probability ensembles, threshold 0.5. No test data was read. Decided 2026-09-17T18:36:12+05:30.

## Ensembles

| Arm | CodeBERT branch | F1 | Precision | Recall | ROC-AUC | PR-AUC | TP/FP/FN/TN |
|---|---|---|---|---|---|---|---|
| nocodebert | no | 0.7706 | 0.8077 | 0.7368 | 0.8621 | 0.8908 | 42/10/15/41 |
| ctrl_codebert | yes | 0.7500 | 0.8298 | 0.6842 | 0.8641 | 0.9015 | 39/8/18/43 |

## Individual runs

| Arm | Seed | F1 | Precision | Recall | ROC-AUC |
|---|---|---|---|---|---|
| nocodebert | 201 | 0.7748 | 0.7963 | 0.7544 | 0.8208 |
| nocodebert | 202 | 0.7000 | 0.8140 | 0.6140 | 0.8672 |
| nocodebert | 203 | 0.8034 | 0.7833 | 0.8246 | 0.8768 |
| nocodebert | 204 | 0.7455 | 0.7736 | 0.7193 | 0.8170 |
| nocodebert | 205 | 0.7778 | 0.8235 | 0.7368 | 0.8724 |
| nocodebert | mean ± sd | 0.7603 ± 0.0395 | 0.7981 ± 0.0207 | 0.7298 ± 0.0761 | 0.8508 ± 0.0294 |
| ctrl_codebert | 201 | 0.7083 | 0.8718 | 0.5965 | 0.8603 |
| ctrl_codebert | 202 | 0.8039 | 0.9111 | 0.7193 | 0.8762 |
| ctrl_codebert | 203 | 0.7350 | 0.7167 | 0.7544 | 0.8201 |
| ctrl_codebert | 204 | 0.7810 | 0.8542 | 0.7193 | 0.8827 |
| ctrl_codebert | 205 | 0.7358 | 0.7959 | 0.6842 | 0.8507 |
| ctrl_codebert | mean ± sd | 0.7528 ± 0.0387 | 0.8299 ± 0.0757 | 0.6947 ± 0.0603 | 0.8580 ± 0.0247 |

## Paired comparison (nocodebert − ctrl_codebert)

- ΔF1 = +0.0206, paired-bootstrap 95% CI [-0.0200, +0.0688] (10000 of 10,000 resamples used)
- ΔAUC = -0.0021 (descriptive CI [-0.0260, +0.0216])

## Decision (frozen rule)

- delta_f1_val > 0: yes
- delta_f1_val_ci95_low > 0: no
- delta_auc_val >= 0: no

**retain_codebert** — selected architecture: codebert (vfinal_work stays final)
