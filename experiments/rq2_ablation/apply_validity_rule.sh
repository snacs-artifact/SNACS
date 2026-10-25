#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ARM="${1:?usage: apply_validity_rule.sh <arm> <slot 201..205>}"; SLOT="${2:?slot}"
case "$SLOT" in 201|202|203|204|205) ;; *) echo "slot must be 201..205"; exit 9 ;; esac
MAXSEED=215
LOG="$HERE/logs_failed/VALIDITY_RULE.log"
mkdir -p "$HERE/runs_failed/$ARM" "$HERE/logs_failed/$ARM" "$HERE/runs/$ARM"
say(){ echo "[$(date '+%m-%d %H:%M:%S')] [$ARM slot $SLOT] $*" | tee -a "$LOG"; }

seedfile="$HERE/runs/$ARM/SEEDS.json"
current_seed(){ python - "$seedfile" "$SLOT" <<'PY'
import json, os, sys
p, slot = sys.argv[1], sys.argv[2]
print(json.load(open(p))["slots"].get(slot, slot) if os.path.exists(p) else slot)
PY
}
set_seed(){ python - "$seedfile" "$SLOT" "$1" "$2" <<'PY'
import json, os, sys
p, slot, new, old = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
d = json.load(open(p)) if os.path.exists(p) else {"slots": {str(s): s for s in range(201, 206)}, "replacements": []}
d["slots"][slot] = int(new)
d["replacements"].append({"slot": int(slot), "failed_seed": int(old), "replaced_by": int(new),
    "reason": "training collapse on validation (constant prediction, validation AUC 0.5) in two attempts"})
json.dump(d, open(p, "w"), indent=1)
PY
}
attempts(){ ls -d "$HERE/runs_failed/$ARM/final_init$1_attempt"* 2>/dev/null | wc -l; }
used(){  # every seed this arm has ever used, in a slot or in the archive
  { python - "$seedfile" <<'PY'
import json, os, sys
p = sys.argv[1]
print(" ".join(str(v) for v in json.load(open(p))["slots"].values()) if os.path.exists(p) else "201 202 203 204 205")
PY
    ls -d "$HERE/runs_failed/$ARM"/final_init* 2>/dev/null | sed 's#.*final_init\([0-9]*\).*#\1#'; } | tr ' ' '\n' | sort -u; }
train(){ "$HERE/run_ablation_arm.sh" "$ARM" "$1"; }

while :; do
  S=$(current_seed)
  [ -f "$HERE/runs/$ARM/final_init$S/stage2/stage2_best.pt" ] || { say "training seed $S"; train "$S" || { say "training seed $S did not complete - STOP"; exit 4; }; }
  python "$HERE/scripts/check_validity.py" --arm "$ARM" --seed "$S" > /dev/null; rc=$?
  [ $rc -eq 0 ] && { say "seed $S is valid - slot settled"; exit 0; }
  [ $rc -eq 3 ] || { say "seed $S could not be checked (rc $rc) - STOP"; exit 5; }
  n=$(( $(attempts "$S") + 1 ))
  mv "$HERE/runs/$ARM/final_init$S" "$HERE/runs_failed/$ARM/final_init${S}_attempt$n"
  mv "$HERE/logs/$ARM/s$S" "$HERE/logs_failed/$ARM/s${S}_attempt$n"
  say "seed $S FAILED the validity check (attempt $n); archived"
  [ "$n" -lt 2 ] && continue                                  # rule step 1: same seed once more
  rec=$(ls "$HERE"/runs/$ARM/final_init*/ARM.json "$HERE"/runs_failed/$ARM/final_init*/ARM.json 2>/dev/null | head -1)
  start=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['start_stage'])" "$rec")
  [ "$start" -eq 0 ] || { say "arm starts from a shipped stage; no shipped checkpoint exists for a new seed - STOP"; exit 6; }
  next=206; while used | grep -qx "$next"; do next=$((next + 1)); done
  [ "$next" -le $MAXSEED ] || { say "no unused seed left up to $MAXSEED - STOP"; exit 7; }
  set_seed "$next" "$S"
  say "seed $S failed twice; slot $SLOT now uses seed $next"
done
