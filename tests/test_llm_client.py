"""The real client talks to an OpenAI-compatible server: check the request it sends."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from kgcoevo.llm.client import LLMClient, LLMConfig

SEEN = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        out = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
               "choices": [{"index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "<think>hidden</think>{\"ok\": true}"}}],
               "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_client_request_and_thinking_strip(monkeypatch):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = LLMConfig(base_url=f"http://127.0.0.1:{srv.server_port}/v1", model="Qwen/Qwen3.5-9B")
    client = LLMClient(cfg)
    out = asyncio.run(client.chat([{"role": "user", "content": "hi"}], seed=3))
    srv.shutdown()
    assert out == '{"ok": true}'
    body = SEEN[-1]
    assert body["top_k"] == 20 and body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["temperature"] == 0.7 and body["top_p"] == 0.8 and body["seed"] == 3
    assert client.usage["prompt_tokens"] == 11
