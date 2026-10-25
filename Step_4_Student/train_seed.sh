#!/usr/bin/env bash
# Train ONE seed of the final model (K = 2) on the frozen 753-contract dataset.
#   usage: ./train_seed.sh <seed>            seeds: 201 202 203 204 205
#   GPU instead of CPU:  TRAIN_DEVICE=gpu ./train_seed.sh <seed>
#
# Writes to Step_4_Student/checkpoints_retrained/ and logs_retrained/.
# It never touches the shipped SNACS/checkpoints_final/.
set -u
cd "$(dirname "$(readlink -f "$0")")"
ROOT=$(dirname "$PWD")

INIT="${1:?usage: train_seed.sh <seed>  (201..205)}"
case "$INIT" in 201|202|203|204|205) ;; *) echo "refusing unexpected seed '$INIT'"; exit 9 ;; esac

# Default: CPU with 2 threads per seed, as for the shipped checkpoints. Training is
# not bit-repeatable, so a retrain lands close to, not on, the shipped result.
case "${TRAIN_DEVICE:-cpu}" in
  cpu) export CUDA_VISIBLE_DEVICES=""                     # utils/config.py then picks "cpu"
       export OMP_NUM_THREADS=${TRAIN_THREADS:-2} MKL_NUM_THREADS=${TRAIN_THREADS:-2} ;;
  gpu) : ;;                                               # uses cuda if torch can see it
  *)   echo "TRAIN_DEVICE must be cpu or gpu"; exit 9 ;;
esac

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export SPLIT_FILE=$ROOT/Dataset/FINAL_CLEAN_DATASET/split.json
export SD_EDGE_WEIGHT=0.7
# The CodeBERT channel. If unset, load_text_emb() returns ZEROS SILENTLY and the
# model scores lower with no error, so it is exported here and asserted below.
export V7_CODEBERT_DIR=$ROOT/Step_2_Preprocessing/codebert_final
export V7_TEXT_PROJ=128

LAB=config/labels_final_clean.csv
ENC=$ROOT/Step_2_Preprocessing/encoded_pyg
SDG=$ROOT/Step_1_SDG/sdg
CFG=config/best_stage0_config.json          # K = 2; stages 1 and 2 inherit K from it
CACHE=$ROOT/Step_3_Teacher/teacher_cache
PAIRS=config/train_pairs_empty.json
D=$PWD/checkpoints_retrained/final_init${INIT}
LOGD=$PWD/logs_retrained/s${INIT}

mkdir -p "$LOGD" "$D"/stage0 "$D"/stage1 "$D"/stage2
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOGD"/progress.log; }
log "===== SEED ${INIT} START  device=${TRAIN_DEVICE:-cpu} ====="

for p in "$SPLIT_FILE" "$LAB" "$CFG" "$PAIRS"; do
  [ -f "$p" ] || { log "MISSING $p - ABORT"; exit 1; }
done
python - <<'PY' || { log "preflight FAILED - ABORT"; exit 1; }
import json,os,torch
sp=json.load(open(os.environ["SPLIT_FILE"]))
n=(len(sp["train"]),len(sp["val"]),len(sp["test"]))
assert n==(524,108,121), f"split is {n}, expected (524,108,121)"
root=os.path.dirname(os.getcwd())
enc=f"{root}/Step_2_Preprocessing/encoded_pyg"; cb=os.environ["V7_CODEBERT_DIR"]; ca=f"{root}/Step_3_Teacher/teacher_cache"
names=[x for k in ("train","val","test") for x in sp[k]]
for tag,d in (("encodings",enc),("CodeBERT",cb),("teacher cache",ca)):
    miss=[x for x in names if not os.path.exists(f"{d}/{x}.pt")]
    assert not miss, f"{len(miss)} contracts missing from {tag} (e.g. {miss[:3]})"
g=torch.load(f"{enc}/{names[0]}.pt",map_location="cpu",weights_only=False)
e=torch.load(f"{cb}/{names[0]}.pt",map_location="cpu")
assert len(e["ids"])==g.x.shape[0], "CodeBERT/encoding node-count mismatch"
assert float(e["emb"].abs().sum())>0, "CodeBERT features are all zero"
K=json.load(open("config/best_stage0_config.json"))["K"]
assert K==2, f"config/best_stage0_config.json has K={K}; the final model is K=2"
print(f"[preflight] 524/108/121; encodings, CodeBERT and teacher cache complete; text features live; K={K}")
PY
# Always overwrite: a stale config left by an earlier run would silently fix K.
cp "$CFG" "$D"/stage0/best_stage0_config.json
log "preflight OK"

export RUN_SEED=$INIT
run(){ local lg=$1; shift; log "-> $lg"; "$@" > "$lg" 2>&1
  grep -q 'TEST EVALUATION' "$lg" 2>/dev/null || { log "FAILED: $lg"; return 1; }; }

run "$LOGD"/stage0.log python training/stage0_label_pretraining.py --encoded_folder $ENC --labels_file $LAB \
    --checkpoint_dir $D/stage0 --config_out $D/stage0/best_stage0_config.json || { log "STAGE 0 FAILED"; exit 2; }
log "stage0 done"
run "$LOGD"/stage1.log python training/stage1_teacher_alignment.py --encoded_folder $ENC --labels_file $LAB \
    --sdg_folder $SDG --stage0_checkpoint $D/stage0/stage0_best.pt \
    --stage0_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage1 --teacher_cache_dir $CACHE || { log "STAGE 1 FAILED"; exit 3; }
log "stage1 done"
run "$LOGD"/stage2.log python training/stage2_masked_structure.py --pairs_json $PAIRS \
    --pair_loss_weight 0 --pair_margin 0.2 --pair_n_sample 8 \
    --encoded_folder $ENC --labels_file $LAB \
    --stage1_checkpoint $D/stage1/stage1_best.pt \
    --stage1_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage2 || { log "STAGE 2 FAILED"; exit 4; }
log "stage2 done"
log "===== SEED ${INIT} COMPLETE ====="
