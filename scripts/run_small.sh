#!/usr/bin/env bash
# Whole 2-day pipeline (configs/small.yaml). Every stage is resumable: re-run the same command
# after a Colab disconnect. Pass extra overrides as arguments, e.g. paths.work_dir=/content/drive/...
set -euo pipefail
CFG=${CFG:-configs/small.yaml}
SET=("$@")
python -m experiments.exp1.prepare      --config "$CFG" --set "${SET[@]}"
python -m experiments.exp1.run          --config "$CFG" --set "${SET[@]}" --stages probe mode_a mode_b gap_tasks checks judge solver
python -m experiments.exp1.export_audit --config "$CFG" --set "${SET[@]}"
python -m experiments.exp1.analyze      --config "$CFG" --set "${SET[@]}"
python -m experiments.exp2.build_cases  --config "$CFG" --set "${SET[@]}" --stages pool cases
python -m experiments.exp2.run          --config "$CFG" --set "${SET[@]}" --stages curator locality
python -m experiments.exp2.analyze      --config "$CFG" --set "${SET[@]}"
