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

# Large/high-churn machine-only contracts use compact JSON. Whitespace is not
# part of their contract, so decoded objects and schemas stay identical while
# repeated process-boundary reads/writes carry fewer bytes. Human-facing and
# small governance artifacts remain pretty-printed for operator readability.
_COMPACT_MACHINE_ARTIFACTS = frozenset({
    "predictions_v4.json",
    "predictions_base_hot_cache_v4.json",
    "competitive_load_v4.json",
    "tactical_serving_v4.json",
    "owned_challenger_decision_v4.json",
    "wc_package_audit_v4.json",
    "serving_payload_v4.json",
    "effective_plan_v4.json",
    "framework_health_v4.json",
    "publication_integrity_v4.json",
})


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
    """Atomically write JSON without changing the decoded artifact contract.

    Large/high-churn machine runtime artifacts use compact JSON because
    whitespace is not part of their contract and repeatedly carrying it across
    process boundaries is costly. Both codecs preserve the same Python object
    structure and UTF-8 semantics, with stdlib fallbacks retained for minimal
    environments.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    dump = _dumps_compact if path.name in _COMPACT_MACHINE_ARTIFACTS else _dumps_pretty
    tmp.write_bytes(dump(payload))
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
