#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT/Step_4_Student"

ARM="${1:?usage: run_split_arm.sh <80_20|70_30> <seed 201..205>}"; INIT="${2:?seed}"
case "$ARM" in 80_20|70_30) ;; *) echo "unknown arm '$ARM'"; exit 9 ;; esac
case "$INIT" in 201|202|203|204|205) ;; *) echo "seed must be 201..205"; exit 9 ;; esac
SPLIT=$HERE/splits/split_${ARM}.json
[ -f "$SPLIT" ] || { echo "missing $SPLIT - run scripts/make_split.py first"; exit 1; }

case "${TRAIN_DEVICE:-cpu}" in
  cpu) export CUDA_VISIBLE_DEVICES=""
       export OMP_NUM_THREADS=${TRAIN_THREADS:-2} MKL_NUM_THREADS=${TRAIN_THREADS:-2} ;;
  gpu) : ;;
  *)   echo "TRAIN_DEVICE must be cpu or gpu"; exit 9 ;;
esac

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export SPLIT_FILE=$SPLIT
export SD_EDGE_WEIGHT=0.7
export V7_CODEBERT_DIR=$ROOT/Step_2_Preprocessing/codebert_final
export V7_TEXT_PROJ=128
export RUN_SEED=$INIT
unset DROP_RELATIONS ABLATE_LOSS TAINT_ONLY_TEACHER TEACHER_NO_LIMIT_CHECKS \
      TEACHER_LAMBDA_N TEACHER_LAMBDA_T V9_INVERSE SPLIT_SEED TUNE_METRIC

LAB=config/labels_final_clean.csv
ENC=$ROOT/Step_2_Preprocessing/encoded_pyg
SDG=$ROOT/Step_1_SDG/sdg
CFG=config/best_stage0_config.json              # the final K = 2 config, unchanged
CACHE=$ROOT/Step_3_Teacher/teacher_cache                        # read-only: the teacher does not depend on the split
PAIRS=config/train_pairs_empty.json
D=$HERE/runs/${ARM}/final_init${INIT}
LOGD=$HERE/logs/${ARM}/s${INIT}
mkdir -p "$LOGD" "$D"/stage0 "$D"/stage1 "$D"/stage2
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOGD"/progress.log; }
log "===== SPLIT $ARM SEED $INIT START  device=${TRAIN_DEVICE:-cpu} threads=${TRAIN_THREADS:-2} ====="

ARM="$ARM" python - <<'PY' || { log "preflight FAILED - ABORT"; exit 1; }
import json, os, torch
sp = json.load(open(os.environ["SPLIT_FILE"]))
names = [x for k in ("train", "val", "test") for x in sp[k]]
assert len(names) == 753 and len(set(names)) == 753, "the arm split must cover the 753 contracts exactly once"
frozen = json.load(open(f"{os.path.dirname(os.getcwd())}/Dataset/FINAL_CLEAN_DATASET/split.json"))
assert (len(frozen["train"]), len(frozen["val"]), len(frozen["test"])) == (524, 108, 121), \
    "the frozen split has been modified - ABORT"
root = os.path.dirname(os.getcwd())
enc = f"{root}/Step_2_Preprocessing/encoded_pyg"; cb = os.environ["V7_CODEBERT_DIR"]
for tag, d in (("encodings", enc), ("CodeBERT", cb), ("teacher cache", f"{root}/Step_3_Teacher/teacher_cache")):
    miss = [x for x in names if not os.path.exists(f"{d}/{x}.pt")]
    assert not miss, f"{len(miss)} contracts missing from {tag} (e.g. {miss[:3]})"
g = torch.load(f"{enc}/{names[0]}.pt", map_location="cpu", weights_only=False)
e = torch.load(f"{cb}/{names[0]}.pt", map_location="cpu")
assert len(e["ids"]) == g.x.shape[0], "CodeBERT/encoding node-count mismatch"
assert float(e["emb"].abs().sum()) > 0, "CodeBERT features are all zero"
c = json.load(open("config/best_stage0_config.json"))
assert c["K"] == 2 and c["lr"] == 0.001, f"config is not the final one (K={c['K']}, lr={c['lr']})"
n = tuple(len(sp[k]) for k in ("train", "val", "test"))
print(f"[preflight] split {os.environ['ARM']}: {n[0]}/{n[1]}/{n[2]}; inputs complete; "
      f"text features live; K=2, lr=1e-3 unchanged; frozen split untouched")
PY
log "preflight OK"

cp "$CFG" "$D"/stage0/best_stage0_config.json
python - "$D/ARM.json" <<PY
import json, sys
sp = json.load(open("$SPLIT"))
json.dump({"study": "split_ratio", "arm": "$ARM", "seed": $INIT,
           "split": "experiments/sensitivity_split_ratio/splits/split_${ARM}.json",
           "counts": {k: len(sp[k]) for k in ("train", "val", "test")},
           "K": 2, "lr": 0.001, "sd_edge_weight": "0.7",
           "device": "${TRAIN_DEVICE:-cpu}", "threads": "${TRAIN_THREADS:-2}",
           "env": {}}, open(sys.argv[1], "w"), indent=1)
PY

run(){ local lg=$1; shift; log "-> $lg"; "$@" > "$lg" 2>&1
  grep -q 'TEST EVALUATION' "$lg" 2>/dev/null || { log "FAILED: $lg"; return 1; }; }
done_stage(){ [ -f "$D/stage$1/stage$1_best.pt" ] && grep -q 'TEST EVALUATION' "$LOGD/stage$1.log" 2>/dev/null; }

done_stage 0 || run "$LOGD"/stage0.log python training/stage0_label_pretraining.py \
    --encoded_folder $ENC --labels_file $LAB \
    --checkpoint_dir $D/stage0 --config_out $D/stage0/best_stage0_config.json \
    || { log "STAGE 0 FAILED"; exit 2; }
log "stage0 done"
done_stage 1 || run "$LOGD"/stage1.log python training/stage1_teacher_alignment.py \
    --encoded_folder $ENC --labels_file $LAB \
    --sdg_folder $SDG --stage0_checkpoint $D/stage0/stage0_best.pt \
    --stage0_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage1 --teacher_cache_dir $CACHE \
    || { log "STAGE 1 FAILED"; exit 3; }
log "stage1 done"
done_stage 2 || run "$LOGD"/stage2.log python training/stage2_masked_structure.py --pairs_json $PAIRS \
    --pair_loss_weight 0 --pair_margin 0.2 --pair_n_sample 8 \
    --encoded_folder $ENC --labels_file $LAB \
    --stage1_checkpoint $D/stage1/stage1_best.pt \
    --stage1_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage2 \
    || { log "STAGE 2 FAILED"; exit 4; }
log "stage2 done"
log "===== SPLIT $ARM SEED $INIT COMPLETE ====="
