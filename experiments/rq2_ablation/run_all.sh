#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
JOBS=${JOBS:-26}
SLOTS="201 202 203 204 205"
mkdir -p "$HERE/logs" "$HERE/results"
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$HERE/logs/run_all.log"; }

ARMS_S0="nocontains noseq nocf nodd nogd nosd ctrl_full"
ARMS_S1="taint_only wo_teachersup wo_graph_teacher wo_node wo_traj ctrl_from_s0"
ARMS_S2="wo_maskedstruct ctrl_from_s1"
ALL="$ARMS_S0 $ARMS_S1 $ARMS_S2"

say "step 1: teacher caches"
"$HERE/build_teacher_caches.sh" | tee -a "$HERE/logs/run_all.log" || { say "teacher caches FAILED"; exit 1; }

say "step 2: verify switches and caches"
python "$HERE/scripts/verify_switches.py" > "$HERE/results/VERIFY_SWITCHES.txt" 2>&1 \
  || { say "switch verification FAILED - see results/VERIFY_SWITCHES.txt"; exit 1; }
python "$HERE/scripts/check_teacher_caches.py" >> "$HERE/logs/run_all.log" 2>&1 \
  || { say "teacher cache check FAILED - see logs/run_all.log"; exit 1; }

seed_of(){  # the seed a slot currently uses (runs/<arm>/SEEDS.json after a replacement)
  python -c "import json,os,sys; p=sys.argv[1]; print(json.load(open(p))['slots'][sys.argv[2]] if os.path.exists(p) else sys.argv[2])" \
    "$HERE/runs/$1/SEEDS.json" "$2"
}
queue(){  # every arm x slot whose run has not finished stage 2
  for a in $ALL; do for slot in $SLOTS; do
    s=$(seed_of "$a" "$slot")
    grep -q 'TEST EVALUATION' "$HERE/logs/$a/s$s/stage2.log" 2>/dev/null \
      && [ -f "$HERE/runs/$a/final_init$s/stage2/stage2_best.pt" ] || echo "$a $s"
  done; done
}

for pass in 0 1 2; do
  queue > "$HERE/logs/queue_pass$pass.txt"
  n=$(grep -c . "$HERE/logs/queue_pass$pass.txt")
  [ "$n" -eq 0 ] && break
  say "step 3: training pass $pass - $n job(s), $JOBS at a time"
  xargs -a "$HERE/logs/queue_pass$pass.txt" -P "$JOBS" -L 1 "$HERE/run_ablation_arm.sh" \
    >> "$HERE/logs/run_all.log" 2>&1
done
left=$(queue | grep -c .)
[ "$left" -eq 0 ] || { say "STOP: $left job(s) still unfinished after repair passes: $(queue | tr '\n' ';')"; exit 2; }

say "step 4: training-validity rule (validation data only)"
python "$HERE/scripts/check_validity.py" --all > "$HERE/logs/collapsed_runs.txt" 2>> "$HERE/logs/run_all.log"
if [ -s "$HERE/logs/collapsed_runs.txt" ]; then
  say "collapsed run(s): $(tr '\n' ';' < "$HERE/logs/collapsed_runs.txt") - applying the rule"
  xargs -a "$HERE/logs/collapsed_runs.txt" -P "$JOBS" -L 1 "$HERE/apply_validity_rule.sh" >> "$HERE/logs/run_all.log" 2>&1
  python "$HERE/scripts/check_validity.py" --all > "$HERE/logs/collapsed_runs.txt" 2>> "$HERE/logs/run_all.log" \
    || { say "STOP: still collapsed after the rule: $(tr '\n' ';' < "$HERE/logs/collapsed_runs.txt")"; exit 3; }
fi
say "all 75 slots hold a valid run"

say "step 5: scoring on test (every arm is re-scored; about 2 minutes each) and tables"
for a in $ALL full_shipped; do echo "$a"; done \
  | xargs -P 8 -I{} python "$HERE/scripts/score_arm.py" --arm {} >> "$HERE/logs/run_all.log" 2>&1
python "$HERE/scripts/make_tables.py" 2>&1 | tee -a "$HERE/logs/run_all.log"
say "ALL DONE"
