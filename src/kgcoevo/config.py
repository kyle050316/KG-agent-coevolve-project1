"""YAML configs with ``extends`` inheritance, dotted CLI overrides and a run manifest.

The resolved config is written to ``<work_dir>/config.resolved.yaml`` together with environment
information (package versions, git commit, time). Commit and tag the resolved config before the
main run: it is the pre-registration of conditions, sample sizes, metrics and seeds.
"""

from __future__ import annotations

import copy
import datetime as dt
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml


def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_config(path: str | Path, overrides: list[str] | None = None) -> dict:
    path = Path(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "extends" in cfg:
        base = load_config(path.parent / cfg.pop("extends"))
        cfg = deep_merge(base, cfg)
    for ov in overrides or []:
        k, _, v = ov.partition("=")
        node = cfg
        parts = k.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = yaml.safe_load(v)
    return cfg


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def manifest() -> dict[str, Any]:
    pkgs = {}
    for p in ("KoPL", "openai", "vllm", "transformers", "rank-bm25", "numpy", "scipy", "scikit-learn"):
        try:
            pkgs[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pass
    return {"time_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "python": sys.version.split()[0],
            "platform": platform.platform(), "git_commit": _git_commit(), "packages": pkgs}


def save_resolved(cfg: dict, work_dir: str | Path, stage: str) -> None:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "config.resolved.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    with (work_dir / "manifest.jsonl").open("a", encoding="utf-8") as f:
        import json
        f.write(json.dumps({"stage": stage, **manifest()}) + "\n")
