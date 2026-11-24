#!/usr/bin/env bash
# Two-day plan (configs/two_day.yaml). All stages are resumable. Extra --set overrides as arguments.
#   bash scripts/run_two_day.sh prepare  <overrides>   # CPU only (KILT streaming, S, Gw, paths)
#   bash scripts/run_two_day.sh exp1     <overrides>   # ~1.2 GPU-h
#   bash scripts/run_two_day.sh pool     <overrides>   # Exp 2 pool, ~3 GPU-h; can run in parallel with exp1
#   bash scripts/run_two_day.sh exp2     <overrides>   # cases + curator + locality, ~4.5 GPU-h (after exp1 and pool)
set -euo pipefail
CFG=${CFG:-configs/two_day.yaml}
STEP=${1:?usage: run_two_day.sh prepare|exp1|pool|exp2 [overrides]}; shift
SET=("$@")
case "$STEP" in
  prepare)
    python -m experiments.exp1.prepare --config "$CFG" --set "${SET[@]}" \
      --stages kilt region passages support defects paths ;;
  exp1)
    python -m experiments.exp1.run --config "$CFG" --set "${SET[@]}" \
      --stages mode_a mode_b gap_tasks checks judge solver
    python -m experiments.exp1.export_audit --config "$CFG" --set "${SET[@]}"
    python -m experiments.exp1.analyze      --config "$CFG" --set "${SET[@]}" ;;
  pool)
    python -m experiments.exp2.build_cases --config "$CFG" --set "${SET[@]}" --stages pool ;;
  exp2)
    python -m experiments.exp2.build_cases --config "$CFG" --set "${SET[@]}" --stages cases
    python -m experiments.exp2.run         --config "$CFG" --set "${SET[@]}" --stages curator locality
    python -m experiments.exp2.analyze     --config "$CFG" --set "${SET[@]}" ;;
  *) echo "unknown step $STEP"; exit 1 ;;
esac
