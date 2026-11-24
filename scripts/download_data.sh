#!/usr/bin/env bash
# Download the official KQA Pro release (kb.json, train.json, val.json, test.json) into <data>/kqapro.
# Source: README of github.com/shijx12/KQAPro_Baselines (Tsinghua cloud link).
set -euo pipefail
DATA=${1:-data}
mkdir -p "$DATA/kqapro" "$DATA/kilt"
if [ ! -f "$DATA/kqapro/kb.json" ]; then
  wget -O "$DATA/kqapro.zip" "https://cloud.tsinghua.edu.cn/f/04ce81541e704a648b03/?dl=1"
  rm -rf "$DATA/kqapro_tmp" && unzip -q -o "$DATA/kqapro.zip" -d "$DATA/kqapro_tmp"
  find "$DATA/kqapro_tmp" -name "*.json" -exec mv {} "$DATA/kqapro/" \;
  rm -rf "$DATA/kqapro_tmp" "$DATA/kqapro.zip"
fi
ls -lh "$DATA/kqapro"
cat <<MSG
KQA Pro is ready in $DATA/kqapro.
KILT pages are extracted by 'python -m experiments.exp1.prepare --stages kilt', which streams the
~35 GB KILT knowledge source once and keeps only the pages of KB entities (paths.kilt_source).
To avoid streaming twice, you can download it first and point paths.kilt_source to the local file:
  wget -O $DATA/kilt/kilt_knowledgesource.json http://dl.fbaipublicfiles.com/KILT/kilt_knowledgesource.json
MSG
