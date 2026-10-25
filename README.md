# SNACS

**S**anitization-Aware **N**euro-Symbolic learning for **A**ccess-**C**ontrol vulnerability
detection in **S**olidity smart contracts.

SNACS detects access-control vulnerabilities in Solidity smart contracts. Its objectives
are to:

- build an access-control-specific semantic dependence graph (SDG) that captures control
  flow, data dependence, cross-function state dependence and guard scope, together with a
  sanitization-aware dual-state dataflow analysis that separately propagates attacker
  influence and guard or sanitization evidence;
- use this deterministic analysis as a teacher that supervises a relational graph neural
  network (the student) at the node and graph level and through its intermediate
  propagation states, so that the teacher is needed only during training;
- provide an access-control dataset of 753 Solidity contracts from five sources with
  overlap-controlled train, validation and test partitions;
- evaluate the framework against representative access-control and learning-based
  detectors, with a student that needs only the target contract at inference.

This repository contains the dataset, the code of every step, the trained model and the
experiment scripts.

## Layout

```
Dataset/FINAL_CLEAN_DATASET/   753 Solidity contracts, labels, train/val/test split, solc versions
Step_1_SDG/                    Step 1: Solidity -> semantic dependence graph (Slither)
  sdg.tar.gz                   the 753 generated graphs
Step_2_Preprocessing/          Step 2: graph -> node features (attribute encoder, CodeBERT)
  encoded_pyg/, codebert_final/, encoder_transductive.pkl   the generated features
Step_3_Teacher/                Step 3: sanitization-aware taint engine (teacher) and its cache builder
Step_4_Student/                Step 4: relational GNN student: model, curriculum training, evaluation
checkpoints_final/             the trained model (5 seeds x 3 training stages)
experiments/                   one folder per experiment of the paper (Section VI)
  rq2_ablation/                SDG-relation and teacher/objective ablations (RQ2)
  rq2_codebert_ablation/       CodeBERT-feature ablation (RQ2)
  rq3_access_patterns/         performance per access-control pattern (RQ3)
  sensitivity_depth/           number of message-passing steps K
  sensitivity_learning_rate/   learning rate
  sensitivity_split_ratio/     train+validation : test partition
  inference_cost/              processing time per contract
  common/                      scorer shared by the sensitivity studies
requirements.txt               main environment (pinned)
requirements-codebert.txt      CodeBERT environment (pinned)
```

## Setup

Two conda environments: `snacs` for every step except CodeBERT, and `snacs-codebert` for the
CodeBERT features.

```bash
sudo apt install build-essential git
conda create -n snacs python=3.14 -y && conda activate snacs
pip install -r requirements.txt
conda create -n snacs-codebert python=3.8.20 -y && conda activate snacs-codebert
pip install -r requirements-codebert.txt
```

## Quick check

Scores the shipped model on the test set (CPU, a few minutes):

```bash
conda activate snacs
cd Step_4_Student
python evaluate.py --out /tmp/snacs_check.json
```

In the TEST block, the ENSEMBLE line reads
`F1 0.8550  P 0.8485  R 0.8615  Acc 0.8430  AUC 0.9209  PR-AUC 0.9394`.

## Running the pipeline

```bash
conda activate snacs
# Step 1: semantic dependence graphs (both passes are required)
python Step_1_SDG/build_sdg.py
python Step_1_SDG/compiler_ladder.py
# Step 2: node attribute encoding
python Step_2_Preprocessing/sdg_encoder.py --sdg_folder Step_1_SDG/sdg \
    --split_file Dataset/FINAL_CLEAN_DATASET/split.json \
    --model_path Step_2_Preprocessing/encoder_transductive.pkl \
    --out_dir Step_2_Preprocessing/encoded_pyg --mode both
# Step 2: CodeBERT statement features (in snacs-codebert)
conda activate snacs-codebert
python Step_2_Preprocessing/codebert_embed.py
conda activate snacs
# Step 3: teacher (sanitization-aware taint analysis over every SDG)
cd Step_3_Teacher
SD_EDGE_WEIGHT=0.7 python build_teacher_cache.py --sdg_folder ../Step_1_SDG/sdg --cache_dir teacher_cache
# Step 4: student (curriculum training of the five seeds, evaluation)
cd ../Step_4_Student
for s in 201 202 203 204 205; do bash train_seed.sh $s & done; wait
python evaluate.py --checkpoints checkpoints_retrained --out /tmp/retrained.json
```

The shipped graphs and features can be used instead of rebuilding them: unpack the graphs
with `tar -xzf Step_1_SDG/sdg.tar.gz -C Step_1_SDG` and start at Step 3.

## Rebuilding the results

Each folder under `experiments/` holds the scripts of one experiment and, in `results/`,
its per-contract scores and result files. These commands rebuild the result files from the
shipped scores, without retraining (run from the repository root, in `snacs`):

```bash
python experiments/rq2_ablation/scripts/make_tables.py --scores-only
python experiments/rq3_access_patterns/scripts/make_results.py
python experiments/sensitivity_learning_rate/scripts/make_results.py
python experiments/sensitivity_split_ratio/scripts/make_results.py
python experiments/inference_cost/scripts/make_results.py
```

## Rerunning the experiments

Run from the repository root in `snacs`, after Step 3 above (unpacked graphs and teacher
cache).

```bash
# RQ2: SDG-relation and teacher/objective ablations
bash experiments/rq2_ablation/run_all.sh

# RQ2: CodeBERT-feature ablation (validation decision, then test)
rsync -a --exclude runs --exclude logs --exclude results --exclude 'logs_*' \
    experiments/rq2_codebert_ablation/ experiments/rq2_codebert_ablation_rerun/
for p in train decide test; do bash experiments/rq2_codebert_ablation_rerun/run_all.sh $p; done

# Number of message-passing steps K (scored on validation)
for K in 1 2 3 4 5; do for s in 201 202 203 204 205; do
  bash experiments/sensitivity_depth/run_depth_arm.sh $K $s & done; done; wait
for K in 1 2 3 4 5; do (cd Step_4_Student && python evaluate.py --split val \
  --checkpoints ../experiments/sensitivity_depth/runs/K$K \
  --out ../experiments/sensitivity_depth/runs/K$K/VAL_RESULT.json); done

# Learning rate (the 1e-3 arm reuses the ctrl_full runs of rq2_ablation)
for lr in 1e-4 5e-4 5e-3 1e-2; do for s in 201 202 203 204 205; do
  bash experiments/sensitivity_learning_rate/run_lr_arm.sh $lr $s & done; done; wait
S=experiments/common/score_run.py; R=experiments/sensitivity_learning_rate/results/arms
python $S --checkpoints checkpoints_final --label reported_model --out $R/reported_model.json
python $S --checkpoints experiments/rq2_ablation/runs/ctrl_full --label lr1e-3 --out $R/lr1e-3.json
for lr in 1e-4 5e-4 5e-3 1e-2; do python $S --checkpoints experiments/sensitivity_learning_rate/runs/lr$lr \
  --label lr$lr --out $R/lr$lr.json; done
python experiments/sensitivity_learning_rate/scripts/make_results.py

# Train+validation : test partition (the paper arm reuses the ctrl_full runs of rq2_ablation)
for a in 80_20 70_30; do for s in 201 202 203 204 205; do
  bash experiments/sensitivity_split_ratio/run_split_arm.sh $a $s & done; done; wait
R=experiments/sensitivity_split_ratio/results/arms
python $S --checkpoints checkpoints_final --label reported_model --out $R/reported_model.json
python $S --checkpoints experiments/rq2_ablation/runs/ctrl_full --label paper --out $R/paper.json
for a in 80_20 70_30; do python $S --checkpoints experiments/sensitivity_split_ratio/runs/$a \
  --split-file experiments/sensitivity_split_ratio/splits/split_$a.json --label $a --out $R/$a.json; done
python experiments/sensitivity_split_ratio/scripts/make_results.py

# Processing time per contract (CodeBERT timing needs an otherwise idle GPU)
cd experiments/inference_cost/scripts
python time_sdg.py ../results/sdg_times.json
python time_pipeline.py ../results/pipeline_times.json
PY=/path/to/envs/snacs-codebert/bin/python bash run_codebert.sh
python make_results.py
```
