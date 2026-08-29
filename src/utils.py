from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_data_override = os.getenv("FPL_DATA_DIR")
DATA = Path(_data_override).expanduser().resolve() if _data_override else ROOT / "data"
CONFIG = ROOT / "config"
_JSON_READ_CACHE: dict[Path, tuple[int, int, Any]] = {}
_COMPACT_JSON_ARTIFACTS = {"decision_brief.json"}

def utcnow():
    return datetime.now(timezone.utc)

def iso_now():
    return utcnow().isoformat()

def read_json(path: Path, default=None):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {} if default is None else default
    cached = _JSON_READ_CACHE.get(path)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _JSON_READ_CACHE[path] = (stat.st_mtime_ns, stat.st_size, payload)
        return payload
    except Exception:
        return {} if default is None else default

def atomic_json(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.name in _COMPACT_JSON_ARTIFACTS:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp.write_text(serialized, encoding="utf-8")
    os.replace(tmp, path)
    try:
        stat = path.stat()
        _JSON_READ_CACHE[path] = (stat.st_mtime_ns, stat.st_size, payload)
    except OSError:
        _JSON_READ_CACHE.pop(path, None)

def append_jsonl(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _JSON_READ_CACHE.pop(path, None)

def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except Exception:
        return None
