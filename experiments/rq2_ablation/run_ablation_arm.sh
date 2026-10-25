#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT/Step_4_Student"

ARM="${1:?usage: run_ablation_arm.sh <arm> <seed 201..205>}"; INIT="${2:?seed}"
[[ "$INIT" =~ ^2(0[1-9]|1[0-5])$ ]] || { echo "seed must be 201..205 (206..215 = validity-rule replacements)"; exit 9; }

SHIPPED_CACHE=$ROOT/Step_3_Teacher/teacher_cache
START=0; CACHE=$SHIPPED_CACHE; S1_ENV=""; S2_ENV=""; DROP=""
case "$ARM" in
  nocontains|noseq|nocf|nodd|nogd|nosd)
       START=0; DROP=${ARM#no}; CACHE=$HERE/teacher_caches/$ARM ;;
  taint_only)
       START=1; S1_ENV="TAINT_ONLY_TEACHER=1"; CACHE=$HERE/teacher_caches/taint_only ;;
  wo_teachersup)    START=1; S1_ENV="ABLATE_LOSS=graph_teacher,node,traj" ;;
  wo_graph_teacher) START=1; S1_ENV="ABLATE_LOSS=graph_teacher" ;;
  wo_node)          START=1; S1_ENV="ABLATE_LOSS=node" ;;
  wo_traj)          START=1; S1_ENV="ABLATE_LOSS=traj" ;;
  wo_maskedstruct)  START=2; S2_ENV="ABLATE_LOSS=node_rec,link" ;;
  ctrl_full)        START=0 ;;
  ctrl_from_s0)     START=1 ;;
  ctrl_from_s1)     START=2 ;;
  *) echo "unknown arm '$ARM'"; exit 9 ;;
esac
if [ "$START" -gt 0 ] && [ "$INIT" -gt 205 ]; then
  echo "$ARM starts from a shipped stage; checkpoints_final has no seed $INIT"; exit 9
fi

case "${TRAIN_DEVICE:-cpu}" in
  cpu) export CUDA_VISIBLE_DEVICES=""
       export OMP_NUM_THREADS=${TRAIN_THREADS:-2} MKL_NUM_THREADS=${TRAIN_THREADS:-2} ;;
  gpu) : ;;
  *)   echo "TRAIN_DEVICE must be cpu or gpu"; exit 9 ;;
esac

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export SPLIT_FILE=$ROOT/Dataset/FINAL_CLEAN_DATASET/split.json
export SD_EDGE_WEIGHT=0.7
export V7_CODEBERT_DIR=$ROOT/Step_2_Preprocessing/codebert_final
export V7_TEXT_PROJ=128
export RUN_SEED=$INIT
unset DROP_RELATIONS ABLATE_LOSS TAINT_ONLY_TEACHER TEACHER_NO_LIMIT_CHECKS \
      TEACHER_LAMBDA_N TEACHER_LAMBDA_T V9_INVERSE SPLIT_SEED TUNE_METRIC
[ -n "$DROP" ] && export DROP_RELATIONS=$DROP      # every stage AND scoring

LAB=config/labels_final_clean.csv
ENC=$ROOT/Step_2_Preprocessing/encoded_pyg
SDG=$ROOT/Step_1_SDG/sdg
CFG=config/best_stage0_config.json
PAIRS=config/train_pairs_empty.json
SHIP=$ROOT/checkpoints_final/final_init$INIT
D=$HERE/runs/$ARM/final_init$INIT
LOGD=$HERE/logs/$ARM/s$INIT
mkdir -p "$LOGD" "$D"/stage0 "$D"/stage1 "$D"/stage2
log(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOGD"/progress.log; }
log "===== ARM $ARM SEED $INIT START  start_stage=$START  device=${TRAIN_DEVICE:-cpu}  DROP_RELATIONS=${DROP:-none}  stage1_env=${S1_ENV:-none}  stage2_env=${S2_ENV:-none} ====="

if [ "$START" -le 1 ] && [ "$CACHE" != "$SHIPPED_CACHE" ] && [ ! -f "$CACHE/_PREBUILD_DONE" ]; then
  log "teacher cache $CACHE is not built; run experiments/rq2_ablation/build_teacher_caches.sh first - ABORT"; exit 1
fi

ARM="$ARM" START="$START" CACHE="$CACHE" python - <<'PY' || { log "preflight FAILED - ABORT"; exit 1; }
import json, os, torch
sp = json.load(open(os.environ["SPLIT_FILE"]))
n = (len(sp["train"]), len(sp["val"]), len(sp["test"]))
assert n == (524, 108, 121), f"split is {n}, expected (524,108,121)"
root = os.path.dirname(os.getcwd())
enc = f"{root}/Step_2_Preprocessing/encoded_pyg"; cb = os.environ["V7_CODEBERT_DIR"]
names = [x for k in ("train", "val", "test") for x in sp[k]]
dirs = [("encodings", enc), ("CodeBERT", cb)]
if int(os.environ["START"]) <= 1:
    dirs.append(("teacher cache", os.environ["CACHE"]))
for tag, d in dirs:
    miss = [x for x in names if not os.path.exists(f"{d}/{x}.pt")]
    assert not miss, f"{len(miss)} contracts missing from {tag} (e.g. {miss[:3]})"
g = torch.load(f"{enc}/{names[0]}.pt", map_location="cpu", weights_only=False)
e = torch.load(f"{cb}/{names[0]}.pt", map_location="cpu")
assert len(e["ids"]) == g.x.shape[0], "CodeBERT/encoding node-count mismatch"
assert float(e["emb"].abs().sum()) > 0, "CodeBERT features are all zero"
K = json.load(open("config/best_stage0_config.json"))["K"]
assert K == 2, f"config/best_stage0_config.json has K={K}; the final model is K=2"
if int(os.environ["START"]) <= 1:
    from utils.ablation import teacher_cache_signature, _normalise_signature
    stamp = json.load(open(os.path.join(os.environ["CACHE"], "_ABLATION_STAMP.json")))
    want = teacher_cache_signature()
    want["taint_only_teacher"] = "1" if os.environ["ARM"] == "taint_only" else "0"
    assert _normalise_signature(stamp) == _normalise_signature(want), \
        f"teacher cache stamp {stamp} does not match this arm {want}"
print(f"[preflight] {os.environ['ARM']}: 524/108/121; inputs complete; text features live; K={K}")
PY
log "preflight OK"

python - "$D/ARM.json" <<PY
import json, sys
json.dump({"arm": "$ARM", "seed": $INIT, "start_stage": $START,
           "inherited_from": ("checkpoints_final/final_init$INIT" if $START > 0 else None),
           "env": {"DROP_RELATIONS": "$DROP"} if "$DROP" else {},
           "stage1_env": "$S1_ENV", "stage2_env": "$S2_ENV",
           "teacher_cache": "$CACHE".replace("$ROOT/", ""),
           "device": "${TRAIN_DEVICE:-cpu}", "threads": "${TRAIN_THREADS:-2}",
           "sd_edge_weight": "0.7", "K": 2}, open(sys.argv[1], "w"), indent=1)
PY

run(){ local lg=$1; shift; log "-> $lg"; "$@" > "$lg" 2>&1
  grep -q 'TEST EVALUATION' "$lg" 2>/dev/null || { log "FAILED: $lg"; return 1; }; }
done_stage(){ [ -f "$D/stage$1/stage$1_best.pt" ] && grep -q 'TEST EVALUATION' "$LOGD/stage$1.log" 2>/dev/null; }
inherit(){  # copy a shipped stage into the arm directory (the shipped file is never opened for writing)
  local s=$1
  if [ ! -f "$D/stage$s/.inherited" ]; then
    cp -p "$SHIP"/stage$s/* "$D"/stage$s/ || { log "copy of shipped stage $s FAILED"; exit 5; }
    ( cd "$D/stage$s" && sha256sum stage${s}_best.pt ) > "$D/stage$s/.inherited"
    log "stage $s inherited from checkpoints_final/final_init$INIT/stage$s"
  fi
}

if [ "$START" -ge 1 ]; then
  inherit 0
else
  cp "$CFG" "$D"/stage0/best_stage0_config.json    # pre-seeded: K = 2, no search
  done_stage 0 || run "$LOGD"/stage0.log python training/stage0_label_pretraining.py \
      --encoded_folder $ENC --labels_file $LAB \
      --checkpoint_dir $D/stage0 --config_out $D/stage0/best_stage0_config.json \
      || { log "STAGE 0 FAILED"; exit 2; }
  log "stage0 done"
fi

if [ "$START" -ge 2 ]; then
  inherit 1
else
  done_stage 1 || run "$LOGD"/stage1.log env $S1_ENV python training/stage1_teacher_alignment.py \
      --encoded_folder $ENC --labels_file $LAB \
      --sdg_folder $SDG --stage0_checkpoint $D/stage0/stage0_best.pt \
      --stage0_config $D/stage0/best_stage0_config.json \
      --checkpoint_dir $D/stage1 --teacher_cache_dir $CACHE \
      || { log "STAGE 1 FAILED"; exit 3; }
  log "stage1 done"
fi

done_stage 2 || run "$LOGD"/stage2.log env $S2_ENV python training/stage2_masked_structure.py --pairs_json $PAIRS \
    --pair_loss_weight 0 --pair_margin 0.2 --pair_n_sample 8 \
    --encoded_folder $ENC --labels_file $LAB \
    --stage1_checkpoint $D/stage1/stage1_best.pt \
    --stage1_config $D/stage0/best_stage0_config.json \
    --checkpoint_dir $D/stage2 \
    || { log "STAGE 2 FAILED"; exit 4; }
log "stage2 done"
log "===== ARM $ARM SEED $INIT COMPLETE ====="
