#!/usr/bin/env bash
# One entry point for both experiments. Every stage is resumable: re-run the same command after a
# disconnect and finished items are skipped. Extra --set overrides can follow the step name.
#
#   CFG=configs/pilot.yaml bash scripts/run.sh all          # pilot first (about 30-45 min)
#   bash scripts/run.sh prepare                             # CPU only: KILT pages, regions, S, Gw, paths
#   bash scripts/run.sh exp1                                # Challenger B0/C1/C1know/C2/C3, checks, judge, Solver
#   CFG=configs/exp2.yaml bash scripts/run.sh prepare2      # Exp 2 data only (regions, passages, S), enlarged B
#   bash scripts/run.sh pool                                # Exp 2 Solver pool on G* (can run right after prepare)
#   bash scripts/run.sh exp2                                # cases, Curator (full + no_tool), locality, report
#   bash scripts/run.sh exp1 paths.work_dir=/content/drive/MyDrive/kgcoevo/main   # with an override
#
# The "probe" stage only runs when exp1.probe.enabled is true (configs/extended.yaml).
set -euo pipefail
CFG=${CFG:-configs/main.yaml}
STEP=${1:?usage: run.sh prepare|prepare2|exp1|pool|exp2|all [key=value ...]}; shift
SET=("$@")
run() { python -m "$1" --config "$CFG" --set "${SET[@]}" "${@:2}"; }

prepare() { run experiments.exp1.prepare --stages kilt region passages support defects paths probe; }
prepare2() { run experiments.exp1.prepare --stages kilt region passages support; }
exp1() {
  run experiments.exp1.run --stages probe mode_a mode_b gap_tasks checks judge solver
  run experiments.exp1.export_audit
  run experiments.exp1.analyze
}
pool() { run experiments.exp2.build_cases --stages pool; }
exp2() {
  run experiments.exp2.build_cases --stages cases
  run experiments.exp2.run --stages curator locality
  run experiments.exp2.analyze
}

case "$STEP" in
  prepare|prepare2|exp1|pool|exp2) "$STEP" ;;
  all) prepare; exp1; pool; exp2 ;;
  *) echo "unknown step: $STEP" >&2; exit 1 ;;
esac
