#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
cd "$ROOT/Step_3_Teacher"

ARMS=${*:-"nocontains noseq nocf nodd nogd nosd taint_only"}
WORKERS=${WORKERS:-8}
mkdir -p "$HERE/teacher_caches" "$HERE/logs/teacher_caches"

for ARM in $ARMS; do
  C=$HERE/teacher_caches/$ARM
  [ -f "$C/_PREBUILD_DONE" ] && { echo "[$ARM] already built"; continue; }
  unset DROP_RELATIONS TAINT_ONLY_TEACHER TEACHER_NO_LIMIT_CHECKS ABLATE_LOSS
  case "$ARM" in
    nocontains|noseq|nocf|nodd|nogd|nosd) SW="DROP_RELATIONS=${ARM#no}" ;;
    taint_only) SW="TAINT_ONLY_TEACHER=1" ;;
    *) echo "unknown cache '$ARM'"; exit 9 ;;
  esac
  echo "[$(date '+%m-%d %H:%M:%S')] [$ARM] building with $SW"
  env SD_EDGE_WEIGHT=0.7 $SW python build_teacher_cache.py \
      --sdg_folder "$ROOT/Step_1_SDG/sdg" --cache_dir "$C" --workers "$WORKERS" \
      > "$HERE/logs/teacher_caches/$ARM.log" 2>&1 \
    || { echo "[$ARM] FAILED - see logs/teacher_caches/$ARM.log"; exit 1; }
  n=$(ls "$C"/*.pt | wc -l)
  [ "$n" -eq 753 ] || { echo "[$ARM] has $n entries, expected 753"; exit 1; }
  touch "$C/_PREBUILD_DONE"
  echo "[$(date '+%m-%d %H:%M:%S')] [$ARM] done: $n entries"
done
