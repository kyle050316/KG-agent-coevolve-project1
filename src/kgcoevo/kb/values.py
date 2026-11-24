"""Value formatting that mirrors the official KoPL engine (kopl.util.ValueClass.__str__).

KQA Pro values are dicts: {"type": "string"|"quantity"|"date"|"year", "value": ..., "unit": ...}.
Every string produced here must be byte-identical to what the KoPL engine prints, because
answer keys, comparisons and edit matching are all done on these strings.
"""

from __future__ import annotations

from datetime import date
from typing import Any

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def parse_time(x: Any) -> tuple[str, Any]:
    """Parse a date/year value exactly as kopl.data.KB._parse_value does."""
    s = str(x)
    if "/" in s or ("-" in s and s[0] != "-"):
        sep = "/" if "/" in s else "-"
        p1, p2 = s.find(sep), s.rfind(sep)
        return "date", date(int(s[:p1]), int(s[p1 + 1:p2]), int(s[p2 + 1:]))
    return "year", int(s)


def value_str(v: dict) -> str:
    """Canonical string of a KB value (identical to str(ValueClass) in KoPL)."""
    t = v["type"]
    if t == "string":
        return str(v["value"])
    if t == "quantity":
        x = float(v["value"])
        unit = str(v.get("unit", "1"))
        num: Any = int(x) if x - int(x) < 1e-5 else x  # mirrors KoPL exactly
        return f"{num} {unit}" if unit != "1" else str(num)
    kind, parsed = parse_time(v["value"])
    return parsed.isoformat() if kind == "date" else str(parsed)


def value_kind(v: dict) -> str:
    """Effective kind of a value: string, quantity, date or year."""
    if v["type"] in ("string", "quantity"):
        return v["type"]
    return parse_time(v["value"])[0]


def kopl_input(v: dict) -> str:
    """String accepted by KoPLEngine._parse_key_value for this value."""
    return value_str(v)


def surface_forms(v: dict) -> list[str]:
    """Surface strings under which a value is typically written in Wikipedia prose."""
    kind = value_kind(v)
    if kind == "string":
        return [str(v["value"])]
    if kind == "year":
        return [value_str(v)]
    if kind == "date":
        d = parse_time(v["value"])[1]
        m = MONTHS[d.month - 1]
        return [f"{d.day} {m} {d.year}", f"{m} {d.day}, {d.year}", f"{m} {d.day} {d.year}", d.isoformat()]
    x = float(v["value"])
    if abs(x - round(x)) < 1e-9:
        n = int(round(x))
        return sorted({f"{n:,}", str(n)}, key=len, reverse=True)
    return sorted({str(x), f"{x:,}"}, key=len, reverse=True)


def make_value(kind: str, raw: Any, unit: str | None = None) -> dict:
    """Build a KB value dict."""
    if kind == "quantity":
        return {"type": "quantity", "value": raw, "unit": unit or "1"}
    if kind == "date":
        return {"type": "date", "value": raw.isoformat() if isinstance(raw, date) else str(raw)}
    if kind == "year":
        return {"type": "year", "value": int(raw)}
    return {"type": "string", "value": str(raw)}
