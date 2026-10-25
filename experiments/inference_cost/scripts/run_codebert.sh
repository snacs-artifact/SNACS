#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
PY="${PY:-python}"   # the snacs-codebert interpreter; override with PY=/path/to/python
for k in 1 2 3; do
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 nice -n 10 "$PY" time_codebert.py "../results/codebert_run$k.json"
done
