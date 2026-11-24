"""Resumable async runner: every finished item is appended (and fsynced) to a JSONL file keyed by an id.

Re-running a stage skips ids that are already present, so a Colab disconnect never loses work.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from tqdm import tqdm


def read_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # a partially written last line after a crash
    return out


def write_jsonl(rows: Iterable[dict], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(obj: Any, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def run_jsonl(items: list[dict], worker: Callable[[dict], Awaitable[dict]], out_path: str | Path,
                    key: Callable[[dict], str], concurrency: int = 32, desc: str = "") -> list[dict]:
    """Run ``worker`` on every item not yet in ``out_path``; return all results (old + new)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {r["_key"]: r for r in read_jsonl(out_path) if "_key" in r}
    todo = [it for it in items if key(it) not in done]
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)
    bar = tqdm(total=len(todo), desc=desc or out_path.stem, disable=not todo)
    errors = 0

    async def one(it: dict) -> None:
        nonlocal errors
        async with sem:
            try:
                res = await worker(it)
            except Exception as e:  # noqa: BLE001 - recorded, the run continues
                errors += 1
                res = {"error": f"{type(e).__name__}: {e}"}
        res["_key"] = key(it)
        async with lock:
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            done[res["_key"]] = res
            bar.update(1)

    await asyncio.gather(*(one(it) for it in todo))
    bar.close()
    if errors:
        print(f"[runner] {errors} items failed in {out_path.name}; they are stored with an 'error' field "
              f"and will NOT be retried automatically (delete those lines to retry).")
    return [done[key(it)] for it in items if key(it) in done]
