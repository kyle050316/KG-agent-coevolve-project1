#!/usr/bin/env bash
# Minimal Exp 1 (configs/exp1_min.yaml). Resumable; extra --set overrides can be passed as arguments.
#   Step 1 (CPU runtime is enough):  bash scripts/run_exp1_min.sh prepare  paths.work_dir=...
#   Step 2 (A100 + vLLM running):    bash scripts/run_exp1_min.sh run      paths.work_dir=...
set -euo pipefail
CFG=${CFG:-configs/exp1_min.yaml}
STEP=${1:-all}; shift || true
SET=("$@")
if [[ "$STEP" == "prepare" || "$STEP" == "all" ]]; then
  python -m experiments.exp1.prepare --config "$CFG" --set "${SET[@]}" \
    --stages kilt region passages support defects paths
fi
if [[ "$STEP" == "run" || "$STEP" == "all" ]]; then
  python -m experiments.exp1.run --config "$CFG" --set "${SET[@]}" \
    --stages mode_a mode_b gap_tasks checks judge solver
  python -m experiments.exp1.export_audit --config "$CFG" --set "${SET[@]}"
  python -m experiments.exp1.analyze      --config "$CFG" --set "${SET[@]}"
fi
