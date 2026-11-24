"""CLI helpers shared by experiment scripts."""

from __future__ import annotations

import argparse
import random

from kgcoevo.config import load_config, save_resolved
from kgcoevo.context import Context


def parse_args(description: str, stages: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", required=True, help="YAML config (see configs/)")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE", help="dotted overrides, e.g. exp1.paths.n=50")
    ap.add_argument("--stages", nargs="*", default=["all"], choices=stages + ["all"])
    return ap.parse_args()


def setup(args: argparse.Namespace, stage_name: str, llms: dict | None = None) -> Context:
    cfg = load_config(args.config, args.set)
    save_resolved(cfg, cfg["paths"]["work_dir"], stage_name)
    random.seed(cfg.get("seed", 0))
    return Context(cfg, llms)


def selected(args: argparse.Namespace, stage: str, order: list[str]) -> bool:
    return "all" in args.stages or stage in args.stages
