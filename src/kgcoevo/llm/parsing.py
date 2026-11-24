"""Robust extraction of the first JSON object from model output."""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL)


def extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    dec = json.JSONDecoder()
    for cand in candidates:
        for i, ch in enumerate(cand):
            if ch == "{":
                try:
                    obj, _ = dec.raw_decode(cand[i:])
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    return obj
    return None
