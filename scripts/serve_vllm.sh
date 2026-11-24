#!/usr/bin/env bash
# Serve Qwen3.5-9B (bf16) with vLLM's OpenAI-compatible server on :8000.
# Requires a vLLM release that supports Qwen3.5 (see the model card). Defaults fit one A100 80GB;
# on an A100 40GB use MAX_SEQS=32. Thinking is disabled per request (chat_template_kwargs).
set -euo pipefail
MODEL=${MODEL:-Qwen/Qwen3.5-9B}
PORT=${PORT:-8000}
GPU_UTIL=${GPU_UTIL:-0.90}
MAX_LEN=${MAX_LEN:-32768}
MAX_SEQS=${MAX_SEQS:-64}
exec vllm serve "$MODEL" \
  --served-model-name "$MODEL" \
  --dtype bfloat16 \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-num-seqs "$MAX_SEQS" \
  --enable-prefix-caching \
  --reasoning-parser qwen3 \
  --limit-mm-per-prompt '{"image": 0, "video": 0}' \
  --seed 0 \
  --port "$PORT"
# Older vLLM versions expect: --limit-mm-per-prompt image=0,video=0
