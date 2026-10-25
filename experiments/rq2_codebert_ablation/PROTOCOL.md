# Protocol: CodeBERT branch ablation and architecture decision

Frozen on 2026-09-17, before any model of this experiment was trained.
`PROTOCOL.sha256` holds the SHA-256 of this file and of `protocol.json`; every
script of this experiment checks both and refuses to run if either has changed.

## Question

Does removing the CodeBERT feature branch change detection performance, and
should the final architecture change as a result?

## Configurations

| Arm | What it is |
|---|---|
| `nocodebert` | The final architecture with the CodeBERT branch **removed**: no 768→128 projection, no text parameters, node input = the 32-d encoded SDG features only. Implemented by leaving `V7_CODEBERT_DIR` unset in every stage, so `RelationalGNN` builds no `text_proj` and every text code path is skipped. Nothing is replaced by zeros. |
| `ctrl_codebert` | The final architecture unchanged (CodeBERT branch present), **retrained** under exactly the same conditions as `nocodebert`, in the same batch. This is the control. |

Neither the shipped `checkpoints_final/` nor any earlier retrained control is used
for the decision.

Everything else is identical for both arms and identical to the final model:
- fixed split `Dataset/FINAL_CLEAN_DATASET/split.json` (524 / 108 / 121);
- config `Step_3_GraphLearning/config/best_stage0_config.json` (K = 2, learning
  rate 0.001, AdamW, batch 16, same schedule);
- the three-stage curriculum (stage 0 → stage 1 teacher alignment → stage 2
  masked-structure learning), shipped teacher cache, `SD_EDGE_WEIGHT = 0.7`,
  pairwise loss off;
- five independent runs per arm, seeds 201, 202, 203, 204, 205;
- CPU, 2 threads per run; checkpoints selected on validation loss;
- decision threshold 0.5 (a contract is vulnerable if its score is > 0.5);
- 5-run mean-probability ensemble.

Model code under `Step_3_GraphLearning/` is not modified.

## Integrity checks (before any number is used)

- `nocodebert`: every stage checkpoint has no `text_proj.*` weights and a
  32-d input layer; the training processes ran without `V7_CODEBERT_DIR`.
- `ctrl_codebert`: every stage checkpoint has `text_proj.*` weights and a
  160-d input layer; scoring asserts the CodeBERT features are non-zero.
- Scoring uses 1 CPU thread (multi-thread scoring is not deterministic).

## Training-validity rule (identical for both arms, validation data only)

A run is FAILED only if it is a genuine training collapse: validation ROC-AUC
exactly 0.5 with every validation score on the same side of 0.5. Then:
1. the same seed is trained once more;
2. if it fails again, the slot takes the next unused seed, starting at 206;
3. the first valid replacement is kept. Seeds are never compared on performance.

## Architecture decision (validation data only)

Computed on the 108 validation contracts, from the two 5-run ensembles:

- ΔF1 = F1(`nocodebert`) − F1(`ctrl_codebert`), ensemble predictions at 0.5.
- 95% CI for ΔF1: paired bootstrap over validation contracts. 10,000
  resamples with replacement, `numpy.random.default_rng(22)`, both F1s
  recomputed on the same resample, resamples with only one class skipped,
  2.5th and 97.5th percentiles.
- ΔAUC = ensemble validation ROC-AUC(`nocodebert`) − ensemble validation
  ROC-AUC(`ctrl_codebert`).

**Adopt `nocodebert` as the final architecture if and only if all three hold:**
1. ΔF1 > 0;
2. the lower end of the 95% paired-bootstrap CI for ΔF1 is > 0;
3. ΔAUC ≥ 0.

Otherwise the current CodeBERT architecture is retained, and `nocodebert` is
reported only as an ablation.

Also reported, not used for the decision: per-arm ensemble validation F1,
precision, recall, ROC-AUC, PR-AUC; per-run validation F1, precision, recall and
ROC-AUC with mean and standard deviation (ddof = 1) across the five runs; a
paired-bootstrap CI for ΔAUC. A paired t-test over five seeds is not used.

## Test set

- No test result is read, printed or used before the decision is written.
  The inherited training code prints a "TEST EVALUATION" block into each stage
  log; those blocks are not read. Run completion is detected from the exit
  status and the checkpoint file, never from log contents.
- The decision is written to `results/DECISION.json` and made read-only.
- Only then, `scripts/score_test.py` scores both arms on the 121 test contracts,
  once. It refuses to run without the locked decision and refuses to overwrite
  its output. Reported regardless of direction:
  - the selected architecture's test result;
  - `nocodebert` as an ablation: ensemble test P, R, F1, AUC; ΔF1 against the
    full framework (the shipped model, F1 0.8550) with a paired-bootstrap 95% CI
    over the 121 test contracts (same bootstrap settings); ΔF1 against
    `ctrl_codebert`.
- Tables VI–X and the main architecture are not changed by this experiment.
