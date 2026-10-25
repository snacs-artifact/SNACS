# Protocol amendment 1: location of the experiment and what each outcome means

Written 2026-09-17 17:03 IST, at the author's request, **before any model of this
experiment was trained**. `PROTOCOL.md` and `protocol.json` are unchanged (their
hashes in `PROTOCOL.sha256` still verify). Nothing in this amendment changes the
arms, the training conditions, the validity rule, the decision rule or the test
procedure.

## 1. vfinal_work is frozen

- Every file of `vfinal_work/` was hashed (10,297 files) into
  `FROZEN_RESULTS/vfinal_work_2026-09-17/MANIFEST.sha256` at the repository root
  (SHA-256 of the manifest: `676182c37d07168e7129a36c143c937bf6dc8f7c1822ef72e483d251fb75afce`),
  copied here as `reference/vfinal_work_MANIFEST.sha256`.
- `vfinal_work/` was then made read-only (`chmod -R a-w`).
- This experiment writes nothing into `vfinal_work/`.

## 2. The experiment runs in its own bundle, vnocodebert_work

- `vnocodebert_work/` holds a copy of `vfinal_work/`'s `Dataset/`, `Step_1_SDG/`,
  `Step_2_Preprocessing/` and `Step_3_GraphLearning/` (3,805 files, every one
  byte-identical to the frozen manifest). Nothing is rebuilt: the SDGs, encoded
  graphs, CodeBERT features, teacher cache, configuration and code are the ones
  the final model used. Only the 10 runs of this experiment are trained.
- Not copied: `vfinal_work/checkpoints_final/`, its `FINAL_RESULT.json`, its
  ablation studies and documents, so nothing here can be mistaken for the final
  model.
- The experiment lives at `vnocodebert_work/ablation/codebert/`, the same relative
  location the frozen protocol names.

## 3. Full-framework reference for the test report

`protocol.json` names the full framework as `checkpoints_final` (F1 0.8550). In
this bundle it is read from `reference/vfinal_FINAL_RESULT.json`, a copy of
`vfinal_work/Step_3_GraphLearning/FINAL_RESULT.json` whose SHA-256
(`71b829a1…a6e0`) matches the frozen manifest. `score_test.py` checks that hash.

## 4. What each outcome means (fixed now, before training)

- **Decision = adopt `nocodebert`:** `vnocodebert_work/` becomes the candidate final
  bundle. Its five `nocodebert` runs become the final model, and the dependent
  tables and studies are redone on it later, as a separate step.
  `vfinal_work/` stays frozen as the previous version.
- **Decision = retain CodeBERT:** `vfinal_work/` remains the final model. The
  `nocodebert` result is added to `vfinal_work/ablation/` as an ablation row, in
  the same form as the Tables VII/VIII rows. That is the only write to
  `vfinal_work/`, done by lifting the read-only flag for that folder alone,
  after this experiment is finished.

Either way, Tables VI–X and the main architecture are not changed by this
experiment itself.
