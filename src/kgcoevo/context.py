"""Shared, lazily-loaded experiment state (KBs, executors, documents, LLM clients).

Layout of ``work_dir`` (see README):
    data/region.json  data/passages.jsonl  data/support.jsonl
    data/gw/rate{r}_seed{s}/{kb.json, defects.jsonl, selfcheck.json}
    data/paths/rate{r}_seed{s}.jsonl  data/probe_items.jsonl
    exp1/*.jsonl  exp2/*.jsonl  results/
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from kgcoevo.docs.kilt import load_pages
from kgcoevo.docs.passages import Passage, load_passages
from kgcoevo.docs.retrieval import BM25Index
from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import KBStore, normalize_kb
from kgcoevo.llm.client import LLMClient, LLMConfig
from kgcoevo.runner import read_json, read_jsonl


def rate_tag(rate: float, seed: int) -> str:
    return f"rate{int(round(rate * 100)):02d}_seed{seed}"


class Context:
    def __init__(self, cfg: dict, llms: dict | None = None):
        self.cfg = cfg
        self.work = Path(cfg["paths"]["work_dir"])
        self.data = self.work / "data"
        self._llms = dict(llms or {})
        self._gw: dict[str, KBStore] = {}
        self._gw_exec: dict[str, Executor] = {}

    # -- KQA Pro ------------------------------------------------------------------------------------
    @cached_property
    def gs(self) -> KBStore:
        with open(Path(self.cfg["paths"]["kqapro_dir"]) / "kb.json", encoding="utf-8") as f:
            return KBStore(normalize_kb(json.load(f)), normalized=True)

    @cached_property
    def gs_exec(self) -> Executor:
        return Executor.from_store(self.gs)

    def questions(self, split: str) -> list[dict]:
        p = Path(self.cfg["paths"]["kqapro_dir"]) / f"{split}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    # -- working KGs -------------------------------------------------------------------------------------
    def gw_dir(self, rate: float, seed: int) -> Path:
        return self.data / "gw" / rate_tag(rate, seed)

    def gw(self, rate: float, seed: int) -> KBStore:
        t = rate_tag(rate, seed)
        if t not in self._gw:
            with open(self.gw_dir(rate, seed) / "kb.json", encoding="utf-8") as f:
                self._gw[t] = KBStore(json.load(f), normalized=True)
        return self._gw[t]

    def gw_exec(self, rate: float, seed: int) -> Executor:
        t = rate_tag(rate, seed)
        if t not in self._gw_exec:
            self._gw_exec[t] = Executor.from_store(self.gw(rate, seed))
        return self._gw_exec[t]

    def release_gw(self) -> None:
        self._gw.clear()
        self._gw_exec.clear()

    def defects(self, rate: float, seed: int) -> list[dict]:
        return read_jsonl(self.gw_dir(rate, seed) / "defects.jsonl")

    def paths(self, rate: float, seed: int) -> list[dict]:
        return read_jsonl(self.data / "paths" / f"{rate_tag(rate, seed)}.jsonl")

    # -- documents ---------------------------------------------------------------------------------------
    @cached_property
    def pages(self) -> dict[str, dict]:
        return load_pages(self.cfg["paths"]["kilt_pages"])

    @cached_property
    def passages(self) -> list[Passage]:
        return load_passages(self.data / "passages.jsonl")

    @cached_property
    def index(self) -> BM25Index:
        return BM25Index(self.passages)

    @cached_property
    def region(self) -> dict:
        return read_json(self.data / "region.json")

    @cached_property
    def support(self) -> list[dict]:
        return read_jsonl(self.data / "support.jsonl")

    # -- LLMs -------------------------------------------------------------------------------------------
    def llm(self, role: str):
        """Client for a role in cfg['llm'] (challenger | solver | curator | judge)."""
        if role not in self._llms:
            roles = self.cfg["llm"]
            spec = roles.get(role) or roles["default"]
            if isinstance(spec, str):  # alias to another role
                return self.llm(spec)
            self._llms[role] = LLMClient(LLMConfig.from_dict({**roles.get("default", {}), **spec}))
        return self._llms[role]

    def usage(self) -> dict:
        return {k: dict(v.usage) for k, v in self._llms.items()}
