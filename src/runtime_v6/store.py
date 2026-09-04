from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "v6"
CURRENT = OUT / "current"
NORMALIZED = OUT / "normalized"
EVIDENCE = OUT / "evidence"
HEALTH = OUT / "health"
MANIFEST = OUT / "manifest.json"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_previous_sources() -> dict[str, dict[str, Any]]:
    if not CURRENT.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in CURRENT.glob("*.json"):
        payload = read_json(path)
        if payload and payload.get("source_id"):
            out[str(payload["source_id"])] = payload
    return out


def prune_inactive_sources(active_source_ids: list[str] | tuple[str, ...]) -> list[str]:
    if not CURRENT.exists():
        return []
    active = set(active_source_ids)
    removed: list[str] = []
    for path in CURRENT.glob("*.json"):
        if path.stem in active:
            continue
        removed.append(path.stem)
        path.unlink()
    return sorted(removed)


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def write_source(source_id: str, payload: dict[str, Any]) -> None:
    write_json(CURRENT / f"{source_id}.json", payload, compact=True)
