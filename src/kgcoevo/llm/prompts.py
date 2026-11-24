"""Prompt templates live in ``kgcoevo/prompts/*.txt`` and use ``{{name}}`` placeholders.

Every template starts with a ``### TASK: <name>`` line, which is logged with each call and lets
the test double dispatch on it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources

_VAR = re.compile(r"\{\{(\w+)\}\}")


@lru_cache(maxsize=None)
def load(name: str) -> str:
    return resources.files("kgcoevo").joinpath("prompts", f"{name}.txt").read_text(encoding="utf-8")


def render(name: str, **kw: object) -> str:
    tpl = load(name)
    missing = sorted(set(_VAR.findall(tpl)) - set(kw))
    if missing:
        raise KeyError(f"template {name} is missing variables {missing}")
    return _VAR.sub(lambda m: str(kw[m.group(1)]), tpl)


def messages(name: str, **kw: object) -> list[dict]:
    return [{"role": "user", "content": render(name, **kw)}]


def task_of(msgs: list[dict]) -> str:
    m = re.search(r"### TASK: (\w+)", msgs[-1]["content"])
    return m.group(1) if m else ""
