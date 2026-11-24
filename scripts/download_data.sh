#!/usr/bin/env bash
# Download the KQA Pro release (kb.json, train.json, val.json) into <data>/kqapro.
# The Tsinghua cloud link in github.com/shijx12/KQAPro_Baselines no longer exists; the same files are
# mirrored on the Hugging Face hub (datasets/drt/kqa_pro, MIT, points to the official repository).
set -euo pipefail
DATA=${1:-data}
HF=https://huggingface.co/datasets/drt/kqa_pro/resolve/main
mkdir -p "$DATA/kqapro" "$DATA/kilt"
for f in kb.json train.json val.json; do
  [ -s "$DATA/kqapro/$f" ] || curl -sSL --fail -o "$DATA/kqapro/$f" "$HF/$f"
done
ls -lh "$DATA/kqapro"
cat <<MSG
KQA Pro is ready in $DATA/kqapro.
KILT pages are extracted by 'python -m experiments.exp1.prepare --stages kilt', which streams the
~35 GB KILT knowledge source once and keeps only the pages of KB entities (paths.kilt_source).
To avoid streaming twice, you can download it first and point paths.kilt_source to the local file:
  curl -L -o $DATA/kilt/kilt_knowledgesource.json http://dl.fbaipublicfiles.com/KILT/kilt_knowledgesource.json
MSG
