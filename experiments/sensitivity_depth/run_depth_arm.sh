#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT/Step_4_Student"

K="${1:?usage: run_depth_arm.sh <K 1..5> <seed 201..205>}"; INIT="${2:?seed}"
case "$K" in 1|2|3|4|5) ;; *) echo "K must be 1..5"; exit 9 ;; esac
case "$INIT" in 201|202|203|204|205) ;; *) echo "seed must be 201..205"; exit 9 ;; esac

case "${TRAIN_DEVICE:-cpu}" in
  cpu) export CUDA_VISIBLE_DEVICES=""; export OMP_NUM_THREADS=${TRAIN_THREADS:-2} MKL_NUM_THREADS=${TRAIN_THREADS:-2} ;;
  gpu) : ;;
  *)   echo "TRAIN_DEVICE must be cpu or gpu"; exit 9 ;;
esac
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export SPLIT_FILE=$ROOT/Dataset/FINAL_CLEAN_DATASET/split.json
export SD_EDGE_WEIGHT=0.7
export V7_CODEBERT_DIR=$ROOT/Step_2_Preprocessing/codebert_final
export V7_TEXT_PROJ=128
export RUN_SEED=$INIT

LAB=config/labels_final_clean.csv
ENC=$ROOT/Step_2_Preprocessing/encoded_pyg
SDG=$ROOT/Step_1_SDG/sdg
PAIRS=config/train_pairs_empty.json
D=$HERE/runs/K$K/final_init$INIT
LOGD=$HERE/logs/K$K/s$INIT
mkdir -p "$LOGD" "$D"/stage0 "$D"/stage1 "$D"/stage2
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOGD"/progress.log; }
log "===== DEPTH ARM K=$K SEED $INIT START  device=${TRAIN_DEVICE:-cpu} ====="

python - "$D/stage0/best_stage0_config.json" "$K" <<'PY' || { log "config FAILED"; exit 1; }
import json, sys
c = json.load(open("config/best_stage0_config.json")); c["K"] = int(sys.argv[2])
json.dump(c, open(sys.argv[1], "w"), indent=4); print(f"[cfg] K = {c['K']}")
PY

run(){ local lg=$1; shift; log "-> $lg"; "$@" > "$lg" 2>&1
  grep -q 'TEST EVALUATION' "$lg" 2>/dev/null || { log "FAILED: $lg"; return 1; }; }
run "$LOGD"/stage0.log python training/stage0_label_pretraining.py --encoded_folder $ENC --labels_file $LAB \
    --checkpoint_dir $D/stage0 --config_out $D/stage0/best_stage0_config.json || exit 2
run "$LOGD"/stage1.log python training/stage1_teacher_alignment.py --encoded_folder $ENC --labels_file $LAB \
    --sdg_folder $SDG --stage0_checkpoint $D/stage0/stage0_best.pt \
    --stage0_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage1 --teacher_cache_dir teacher_cache || exit 3
run "$LOGD"/stage2.log python training/stage2_masked_structure.py --pairs_json $PAIRS \
    --pair_loss_weight 0 --pair_margin 0.2 --pair_n_sample 8 \
    --encoded_folder $ENC --labels_file $LAB \
    --stage1_checkpoint $D/stage1/stage1_best.pt \
    --stage1_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage2 || exit 4
log "===== DEPTH ARM K=$K SEED $INIT COMPLETE ====="
