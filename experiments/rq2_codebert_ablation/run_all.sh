#!/usr/bin/env bash
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
PHASE=${1:?usage: run_all.sh <train|decide|test|all>}
mkdir -p "$HERE/logs" "$HERE/results"
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$HERE/logs/run_all.log"; }
python -c "import sys; sys.path.insert(0,'$HERE/scripts'); import common" || { say "protocol check FAILED"; exit 1; }

train(){
  say "train: 10 jobs"
  for arm in nocodebert ctrl_codebert; do for s in 201 202 203 204 205; do echo "$arm $s"; done; done \
    | xargs -P 10 -L 1 "$HERE/run_codebert_arm.sh" >> "$HERE/logs/run_all.log" 2>&1
  python "$HERE/scripts/check_run.py" --all > "$HERE/logs/collapsed_runs.txt" 2>> "$HERE/logs/run_all.log"; rc=$?
  if [ -s "$HERE/logs/collapsed_runs.txt" ]; then
    say "collapsed: $(tr '\n' ';' < "$HERE/logs/collapsed_runs.txt") - applying the validity rule"
    xargs -a "$HERE/logs/collapsed_runs.txt" -P 10 -L 1 "$HERE/apply_validity_rule.sh" >> "$HERE/logs/run_all.log" 2>&1
    python "$HERE/scripts/check_run.py" --all > "$HERE/logs/collapsed_runs.txt" 2>> "$HERE/logs/run_all.log"; rc=$?
  fi
  [ $rc -eq 0 ] || { say "STOP: not every slot holds a valid run (check_run.py exit $rc, see results/VALIDITY_CHECK.json)"; exit 2; }
  say "train: all 10 slots hold a valid run"
}
decide(){
  say "decide: validation scoring"
  python "$HERE/scripts/score_validation.py" 2>&1 | tee -a "$HERE/logs/run_all.log" || exit 3
  python "$HERE/scripts/decide.py" 2>&1 | tee -a "$HERE/logs/run_all.log" || exit 3
}
test_(){
  say "test: one-time test scoring"
  python "$HERE/scripts/score_test.py" 2>&1 | tee -a "$HERE/logs/run_all.log" || exit 4
}
case "$PHASE" in
  train) train ;;
  decide) decide ;;
  test) test_ ;;
  all) train && decide && test_ ;;
  *) echo "usage: run_all.sh <train|decide|test|all>"; exit 9 ;;
esac
say "$PHASE: done"
