from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import orjson
except ImportError:  # local/minimal environments retain stdlib compatibility
    orjson = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = ROOT / "config"


def utcnow():
    return datetime.now(timezone.utc)


def iso_now():
    return utcnow().isoformat()


def _loads(raw: bytes | str):
    if orjson is not None:
        return orjson.loads(raw)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _dumps_pretty(payload: Any) -> bytes:
    if orjson is not None:
        option = orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY
        return orjson.dumps(payload, option=option)
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _dumps_compact(payload: Any) -> bytes:
    if orjson is not None:
        option = orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY
        return orjson.dumps(payload, option=option)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        return _loads(path.read_bytes())
    except Exception:
        return {} if default is None else default


def atomic_json(path: Path, payload: Any):
    """Atomic pretty JSON write using orjson when installed.

    Pretty UTF-8 output is retained for repository artifacts. The optional codec
    changes only serialization plumbing; object structure and service contracts
    remain unchanged. The stdlib path is deliberately retained as a safe fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_dumps_pretty(payload))
    os.replace(tmp, path)


def append_jsonl(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(_dumps_compact(payload) + b"\n")


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
