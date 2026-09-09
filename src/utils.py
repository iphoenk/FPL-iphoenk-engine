from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_data_override = os.getenv("FPL_DATA_DIR")
DATA = Path(_data_override).expanduser().resolve() if _data_override else ROOT / "data"
CONFIG = ROOT / "config"
_JSON_READ_CACHE: dict[Path, tuple[int, int, Any]] = {}
_JSON_WRITE_PROOF_CACHE: dict[Path, tuple[int, int, str, Any]] = {}
# Machine-consumed high-volume artifacts are compacted to remove avoidable
# serialization/I/O cost. This is representation-only: parsed JSON values,
# schemas, validation and decision semantics are identical.
_COMPACT_JSON_ARTIFACTS = {
    "decision_brief.json",
    "projections.json",
    "package_optimizer.json",
    "team_strength.json",
    "prediction_quality.json",
    "prices.json",
    "price_trajectory.json",
    "price_alerts.json",
    "price_challenger_context.json",
    "dss_watchlist.json",
    "recent_competitive_load.json",
    "dss_operational_evidence.json",
    "framework_health_preflight.json",
    "framework_health.json",
    "external_consensus.json",
    "user_report.json",
    "technical_appendix.json",
    "deep_review_payload.json",
}

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

def trusted_atomic_json(path: Path) -> tuple[bool, Any]:
    """Return an atomic-writer payload only when current bytes match its SHA-256 proof exactly."""
    try:
        stat = path.stat()
    except OSError:
        return False, None
    proof = _JSON_WRITE_PROOF_CACHE.get(path)
    if proof is None or proof[0] != stat.st_mtime_ns or proof[1] != stat.st_size:
        return False, None
    try:
        current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False, None
    if current_digest != proof[2]:
        _JSON_WRITE_PROOF_CACHE.pop(path, None)
        return False, None
    return True, proof[3]

def atomic_json(path: Path, payload: Any, *, compact: bool | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    use_compact = path.name in _COMPACT_JSON_ARTIFACTS if compact is None else bool(compact)
    if use_compact:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    encoded = serialized.encode("utf-8")
    tmp.write_bytes(encoded)
    os.replace(tmp, path)
    try:
        stat = path.stat()
        _JSON_READ_CACHE[path] = (stat.st_mtime_ns, stat.st_size, payload)
        _JSON_WRITE_PROOF_CACHE[path] = (
            stat.st_mtime_ns,
            stat.st_size,
            hashlib.sha256(encoded).hexdigest(),
            payload,
        )
    except OSError:
        _JSON_READ_CACHE.pop(path, None)
        _JSON_WRITE_PROOF_CACHE.pop(path, None)

def append_jsonl(path: Path, payload: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _JSON_READ_CACHE.pop(path, None)
    _JSON_WRITE_PROOF_CACHE.pop(path, None)

def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except Exception:
        return None
