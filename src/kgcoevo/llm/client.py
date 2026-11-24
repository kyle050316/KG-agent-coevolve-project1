"""Async client for OpenAI-compatible endpoints (vLLM / SGLang serving Qwen3.5-9B, or an API judge).

* Decoding parameters are fixed per role in the config and logged with every run.
* For vLLM, Qwen-specific knobs go through ``extra_body``: ``top_k`` and
  ``chat_template_kwargs={"enable_thinking": false}`` (Qwen3.5 thinks by default).
* Any residual ``<think>...</think>`` block is stripped from the returned text.
* ``MockLLM`` has the same interface and is used by the tests.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable

_THINK = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    model: str = "Qwen/Qwen3.5-9B"
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int | None = 20
    presence_penalty: float = 1.5
    max_tokens: int = 1024
    enable_thinking: bool = False
    vllm_extras: bool = True  # send top_k / chat_template_kwargs (set False for hosted APIs)
    concurrency: int = 32
    timeout: float = 300.0
    max_retries: int = 4
    extra_body: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "LLMConfig":
        return LLMConfig(**{k: v for k, v in d.items() if k in LLMConfig.__dataclass_fields__})


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        from openai import AsyncOpenAI

        self.cfg = cfg
        self._client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.timeout, max_retries=0)
        self._sem = asyncio.Semaphore(cfg.concurrency)
        self.usage: Counter = Counter()

    async def chat(self, messages: list[dict], *, temperature: float | None = None, seed: int | None = None,
                   max_tokens: int | None = None) -> str:
        cfg = self.cfg
        body = dict(cfg.extra_body)
        if cfg.vllm_extras:
            if cfg.top_k is not None:
                body["top_k"] = cfg.top_k
            body["chat_template_kwargs"] = {"enable_thinking": cfg.enable_thinking}
        kwargs = dict(model=cfg.model, messages=messages,
                      temperature=cfg.temperature if temperature is None else temperature,
                      top_p=cfg.top_p, max_tokens=max_tokens or cfg.max_tokens, extra_body=body or None)
        if cfg.presence_penalty:
            kwargs["presence_penalty"] = cfg.presence_penalty
        if seed is not None:
            kwargs["seed"] = seed
        delay = 2.0
        async with self._sem:
            for attempt in range(cfg.max_retries + 1):
                try:
                    resp = await self._client.chat.completions.create(**kwargs)
                    if resp.usage:
                        self.usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
                        self.usage["completion_tokens"] += resp.usage.completion_tokens or 0
                    self.usage["calls"] += 1
                    text = resp.choices[0].message.content or ""
                    return _THINK.sub("", text).strip()
                except Exception:  # noqa: BLE001 - network/server errors are retried
                    if attempt == cfg.max_retries:
                        raise
                    await asyncio.sleep(delay + random.random())
                    delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")


class MockLLM:
    """Test double: ``handler(messages, seed) -> str`` (sync or async)."""

    def __init__(self, handler: Callable[[list[dict], int | None], str | Awaitable[str]], name: str = "mock"):
        self.handler = handler
        self.cfg = LLMConfig(model=name)
        self.usage: Counter = Counter()
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict], *, temperature: float | None = None, seed: int | None = None,
                   max_tokens: int | None = None) -> str:
        self.calls.append(messages)
        self.usage["calls"] += 1
        out = self.handler(messages, seed)
        if asyncio.iscoroutine(out):
            out = await out
        return out
