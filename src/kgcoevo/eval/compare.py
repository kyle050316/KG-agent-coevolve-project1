"""Type-aware answer comparison (the ``compare`` tool of the design and the scorer).

Dates are compared after parsing common English formats, numbers after removing thousands
separators (units must match when both sides give one), strings after SQuAD-style normalisation
(lower case, punctuation and articles removed; Rajpurkar et al., 2016).
"""

from __future__ import annotations

import re
import string
from datetime import datetime

_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d")
_NUM = re.compile(r"^([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([A-Za-z][\w\s/%-]*)?$")


def _text(s: str) -> str:
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def canon(s: object) -> str:
    """Canonical comparison key of an answer string."""
    if s is None:
        return ""
    t = str(s).strip().strip("\"'`").rstrip(".").strip()
    for fmt in _DATE_FORMATS:
        try:
            return "date:" + datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    if re.fullmatch(r"-?\d{1,4}", t):
        return "num:" + str(int(t))
    m = _NUM.match(t)
    if m:
        num = float(m.group(1).replace(",", ""))
        unit = _text(m.group(2) or "")
        num_s = str(int(num)) if num == int(num) else repr(num)
        return f"num:{num_s}" + (f"|{unit}" if unit and unit != "1" else "")
    return "txt:" + _text(t)


def answers_equal(a: object, b: object) -> bool:
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return True
    # a unit-less number matches the same number with a unit (models often drop units)
    if ca.startswith("num:") and cb.startswith("num:"):
        return ca.split("|")[0] == cb.split("|")[0] and ("|" not in ca or "|" not in cb)
    return False


def match_any(pred: object, golds: list[str]) -> bool:
    return any(answers_equal(pred, g) for g in golds)


def answer_sets_equal(a: list[str], b: list[str]) -> bool:
    return {canon(x) for x in a} == {canon(x) for x in b}


def mentions(text: str, name: str) -> bool:
    """Case-insensitive whole-word mention test (used by the leak rules)."""
    if not name or not text:
        return False
    return re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", text.lower()) is not None
