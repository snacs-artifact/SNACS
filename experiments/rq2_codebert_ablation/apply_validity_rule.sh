#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ARM="${1:?usage: apply_validity_rule.sh <arm> <slot>}"; SLOT="${2:?slot}"
case "$SLOT" in 201|202|203|204|205) ;; *) echo "slot must be 201..205"; exit 9 ;; esac
LOG="$HERE/logs_failed/VALIDITY_RULE.log"
mkdir -p "$HERE/runs_failed/$ARM" "$HERE/logs_failed/$ARM" "$HERE/runs/$ARM"
say(){ echo "[$(date '+%m-%d %H:%M:%S')] [$ARM slot $SLOT] $*" | tee -a "$LOG"; }
seedfile="$HERE/runs/$ARM/SEEDS.json"

current_seed(){ python -c "import json,os,sys; p=sys.argv[1]; print(json.load(open(p))['slots'][sys.argv[2]] if os.path.exists(p) else sys.argv[2])" "$seedfile" "$SLOT"; }
set_seed(){ python - "$seedfile" "$SLOT" "$1" "$2" <<'PY'
import json, os, sys
p, slot, new, old = sys.argv[1:5]
d = json.load(open(p)) if os.path.exists(p) else {"slots": {str(s): s for s in range(201, 206)}, "replacements": []}
d["slots"][slot] = int(new)
d["replacements"].append({"slot": int(slot), "failed_seed": int(old), "replaced_by": int(new),
                          "reason": "training collapse on validation (AUC 0.5, one-class) in two attempts"})
json.dump(d, open(p, "w"), indent=1)
PY
}
attempts(){ ls -d "$HERE/runs_failed/$ARM/final_init$1_attempt"* 2>/dev/null | wc -l; }
used(){ { python -c "import json,os,sys; p=sys.argv[1]; print(' '.join(str(v) for v in json.load(open(p))['slots'].values()) if os.path.exists(p) else '201 202 203 204 205')" "$seedfile"
          ls -d "$HERE/runs_failed/$ARM"/final_init* 2>/dev/null | sed 's#.*final_init\([0-9]*\).*#\1#'; } | tr ' ' '\n' | sort -u; }

while :; do
  S=$(current_seed)
  if ! python -c "import sys; sys.path.insert(0,'$HERE/scripts'); import common as C; sys.exit(0 if C.run_complete('$ARM', $S) else 1)"; then
    say "training seed $S"; "$HERE/run_codebert_arm.sh" "$ARM" "$S" || { say "training seed $S did not complete - STOP"; exit 4; }
  fi
  python "$HERE/scripts/check_run.py" --arm "$ARM" --seed "$S" > /dev/null; rc=$?
  [ $rc -eq 0 ] && { say "seed $S is valid - slot settled"; exit 0; }
  [ $rc -eq 3 ] || { say "seed $S failed a check that is not a collapse (rc $rc) - STOP"; exit 5; }
  n=$(( $(attempts "$S") + 1 ))
  mv "$HERE/runs/$ARM/final_init$S" "$HERE/runs_failed/$ARM/final_init${S}_attempt$n"
  mv "$HERE/logs/$ARM/s$S" "$HERE/logs_failed/$ARM/s${S}_attempt$n"
  say "seed $S collapsed (attempt $n); archived"
  [ "$n" -lt 2 ] && continue
  next=206; while used | grep -qx "$next"; do next=$((next + 1)); done
  [ "$next" -le 215 ] || { say "no unused seed left up to 215 - STOP"; exit 7; }
  set_seed "$next" "$S"
  say "seed $S collapsed twice; slot $SLOT now uses seed $next"
done
