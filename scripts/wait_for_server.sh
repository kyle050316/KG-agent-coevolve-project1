#!/usr/bin/env bash
# Block until the vLLM server answers (use after starting serve_vllm.sh in the background).
URL=${1:-http://localhost:8000/v1/models}
until curl -sf "$URL" > /dev/null; do sleep 5; done
echo "server ready: $URL"
