#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT/Step_4_Student"

ARM="${1:?usage: run_codebert_arm.sh <nocodebert|ctrl_codebert> <seed>}"; INIT="${2:?seed}"
case "$ARM" in nocodebert|ctrl_codebert) ;; *) echo "unknown arm '$ARM'"; exit 9 ;; esac
[[ "$INIT" =~ ^2(0[1-9]|1[0-5])$ ]] || { echo "seed must be 201..205 (206..215 = validity-rule replacements)"; exit 9; }

export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
export SPLIT_FILE=$ROOT/Dataset/FINAL_CLEAN_DATASET/split.json
export SD_EDGE_WEIGHT=0.7
export RUN_SEED=$INIT
unset DROP_RELATIONS ABLATE_LOSS TAINT_ONLY_TEACHER TEACHER_NO_LIMIT_CHECKS TEACHER_LAMBDA_N \
      TEACHER_LAMBDA_T V9_INVERSE SPLIT_SEED TUNE_METRIC V7_CODEBERT_DIR V7_TEXT_PROJ V7_TEXT_DIM
if [ "$ARM" = ctrl_codebert ]; then
  export V7_CODEBERT_DIR=$ROOT/Step_2_Preprocessing/codebert_final
  export V7_TEXT_PROJ=128
fi

LAB=config/labels_final_clean.csv
ENC=$ROOT/Step_2_Preprocessing/encoded_pyg
SDG=$ROOT/Step_1_SDG/sdg
CFG=config/best_stage0_config.json
PAIRS=config/train_pairs_empty.json
CACHE=$ROOT/Step_3_Teacher/teacher_cache
D=$HERE/runs/$ARM/final_init$INIT
LOGD=$HERE/logs/$ARM/s$INIT
mkdir -p "$LOGD" "$D"/stage0 "$D"/stage1 "$D"/stage2
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOGD"/progress.log; }
log "===== $ARM SEED $INIT START  V7_CODEBERT_DIR=${V7_CODEBERT_DIR:-<unset>} ====="

python -c "import sys; sys.path.insert(0,'$HERE/scripts'); import common" \
  || { log "protocol check FAILED - ABORT"; exit 1; }       # importing common verifies the frozen protocol

ARM="$ARM" python - <<'PY' || { log "preflight FAILED - ABORT"; exit 1; }
import json, os, torch
sp = json.load(open(os.environ["SPLIT_FILE"]))
assert (len(sp["train"]), len(sp["val"]), len(sp["test"])) == (524, 108, 121)
root = os.path.dirname(os.getcwd())
names = [x for k in ("train", "val", "test") for x in sp[k]]
dirs = [("encodings", f"{root}/Step_2_Preprocessing/encoded_pyg"), ("teacher cache", f"{root}/Step_3_Teacher/teacher_cache")]
if os.environ["ARM"] == "ctrl_codebert":
    dirs.append(("CodeBERT", os.environ["V7_CODEBERT_DIR"]))
    e = torch.load(f"{os.environ['V7_CODEBERT_DIR']}/{names[0]}.pt", map_location="cpu")
    assert float(e["emb"].abs().sum()) > 0, "CodeBERT features are all zero"
else:
    assert "V7_CODEBERT_DIR" not in os.environ, "nocodebert must run without V7_CODEBERT_DIR"
for tag, d in dirs:
    miss = [x for x in names if not os.path.exists(f"{d}/{x}.pt")]
    assert not miss, f"{len(miss)} contracts missing from {tag}"
assert json.load(open("config/best_stage0_config.json"))["K"] == 2
print(f"[preflight] {os.environ['ARM']}: split 524/108/121, inputs complete, K=2")
PY
log "preflight OK"

python - "$D/ARM.json" <<PY
import json, sys
json.dump({"arm": "$ARM", "seed": $INIT, "codebert_branch": "$ARM" == "ctrl_codebert",
           "V7_CODEBERT_DIR": "${V7_CODEBERT_DIR:-}".replace("$ROOT/", ""), "device": "cpu", "threads": 2,
           "K": 2, "sd_edge_weight": "0.7", "config": "Step_4_Student/config/best_stage0_config.json"},
          open(sys.argv[1], "w"), indent=1)
PY

stage(){  # stage number, log, command...
  local s=$1 lg=$2; shift 2
  [ -f "$D/stage$s/.done" ] && { log "stage$s already done"; return 0; }
  log "-> stage$s"
  "$@" > "$lg" 2>&1 || { log "stage$s exited non-zero"; return 1; }
  [ -f "$D/stage$s/stage${s}_best.pt" ] || { log "stage$s wrote no checkpoint"; return 1; }
  python -c "import sys; sys.path.insert(0,'$HERE/scripts'); import common; p=common.check_checkpoint('$ARM','$D/stage$s/stage${s}_best.pt'); print(p or 'architecture OK'); sys.exit(1 if p else 0)" \
    >> "$LOGD"/progress.log 2>&1 || { log "stage$s checkpoint has the WRONG architecture - ABORT"; return 1; }
  touch "$D/stage$s/.done"; log "stage$s done"
}

cp "$CFG" "$D"/stage0/best_stage0_config.json
stage 0 "$LOGD"/stage0.log python training/stage0_label_pretraining.py --encoded_folder $ENC --labels_file $LAB \
    --checkpoint_dir $D/stage0 --config_out $D/stage0/best_stage0_config.json || exit 2
stage 1 "$LOGD"/stage1.log python training/stage1_teacher_alignment.py --encoded_folder $ENC --labels_file $LAB \
    --sdg_folder $SDG --stage0_checkpoint $D/stage0/stage0_best.pt \
    --stage0_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage1 --teacher_cache_dir $CACHE || exit 3
stage 2 "$LOGD"/stage2.log python training/stage2_masked_structure.py --pairs_json $PAIRS \
    --pair_loss_weight 0 --pair_margin 0.2 --pair_n_sample 8 \
    --encoded_folder $ENC --labels_file $LAB \
    --stage1_checkpoint $D/stage1/stage1_best.pt \
    --stage1_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage2 || exit 4
log "===== $ARM SEED $INIT COMPLETE ====="
