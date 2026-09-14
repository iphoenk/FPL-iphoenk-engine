from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "v6"
CURRENT = OUT / "current"
NORMALIZED = OUT / "normalized"
EVIDENCE = OUT / "evidence"
HEALTH = OUT / "health"
MANIFEST = OUT / "manifest.json"
CANDIDATE_FREEZE = HEALTH / "candidate_freeze.lock"
_POST_FREEZE_WRITABLE = {
    CANDIDATE_FREEZE,
    HEALTH / "publish_integrity.json",
}


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


def _candidate_is_frozen() -> bool:
    freeze = read_json(CANDIDATE_FREEZE) or {}
    if freeze.get("candidate_state") != "FROZEN":
        return False
    frozen_run_id = str(freeze.get("run_id") or "")
    frozen_run_attempt = str(freeze.get("run_attempt") or "")
    current_run_id = str(os.environ.get("GITHUB_RUN_ID") or "")
    current_run_attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "")
    if frozen_run_id and current_run_id and frozen_run_id != current_run_id:
        return False
    if (
        frozen_run_id
        and current_run_id
        and frozen_run_id == current_run_id
        and frozen_run_attempt
        and current_run_attempt
        and frozen_run_attempt != current_run_attempt
    ):
        return False
    return True


def _assert_post_freeze_write_allowed(path: Path) -> None:
    if not _candidate_is_frozen():
        return
    try:
        path.resolve().relative_to(OUT.resolve())
    except ValueError:
        return
    allowed = {candidate.resolve() for candidate in _POST_FREEZE_WRITABLE}
    if path.resolve() not in allowed:
        raise RuntimeError(f"candidate_frozen_write_rejected:{path.relative_to(OUT).as_posix()}")


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    _assert_post_freeze_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def write_source(source_id: str, payload: dict[str, Any]) -> None:
    write_json(CURRENT / f"{source_id}.json", payload, compact=True)
