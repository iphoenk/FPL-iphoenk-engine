from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.runtime_v3.artifact_contracts import validate_artifact
from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "runtime" / "incremental_reuse.json"
STATE_PATH = DATA / "incremental_reuse_state.json"

_VOLATILE_KEYS = {"generated_at", "fetched_at", "runtime_architecture"}
_PREDICTION_TEAM_FIELDS = (
    "id", "name", "strength_attack_home", "strength_attack_away",
    "strength_defence_home", "strength_defence_away",
)
_PREDICTION_PLAYER_FIELDS = (
    "id", "element_type", "team", "web_name", "now_cost", "status",
    "selected_by_percent", "starts", "minutes", "expected_goals",
    "expected_assists", "bonus", "saves", "chance_of_playing_next_round",
)
_PREDICTION_FIXTURE_FIELDS = (
    "event", "kickoff_time", "finished", "team_h", "team_a",
    "team_h_score", "team_a_score",
)


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "V3_INCREMENTAL_REUSE_V1":
        raise RuntimeError("unexpected incremental reuse registry")
    return payload


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _current_scoring_fixture_live(now: datetime | None = None) -> bool:
    snapshot = read_json(DATA / "official_snapshot.json", {})
    if not isinstance(snapshot, dict):
        return False
    phase = snapshot.get("phase") if isinstance(snapshot.get("phase"), dict) else {}
    scoring_gw = phase.get("scoring_gw")
    if scoring_gw is None:
        latest = read_json(DATA / "latest.json", {})
        latest_phase = latest.get("phase") if isinstance(latest, dict) and isinstance(latest.get("phase"), dict) else {}
        scoring_gw = latest_phase.get("scoring_gw")
    try:
        scoring_gw = int(scoring_gw)
    except (TypeError, ValueError):
        return False

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for fixture in snapshot.get("fixtures") or []:
        if not isinstance(fixture, dict):
            continue
        try:
            event = int(fixture.get("event"))
        except (TypeError, ValueError):
            continue
        if event != scoring_gw:
            continue
        if fixture.get("started") is not True or fixture.get("finished") is True:
            continue
        kickoff = _parse_utc(fixture.get("kickoff_time"))
        if kickoff is None or kickoff > current:
            continue
        return True
    return False


def _service_live_opt_in(service_name: str | None) -> bool:
    if not service_name:
        return False
    spec = (_registry().get("services") or {}).get(service_name)
    return isinstance(spec, dict) and spec.get("allow_during_live") is True


def _any_live_opt_in() -> bool:
    return any(
        isinstance(spec, dict) and spec.get("allow_during_live") is True
        for spec in (_registry().get("services") or {}).values()
    )


def active(profile_name: str, service_name: str | None = None) -> bool:
    registry = _registry()
    policy = registry.get("policy") or {}
    if profile_name not in set(policy.get("enabled_profiles") or []):
        return False
    if policy.get("disable_when_current_scoring_fixture_live") is True and _current_scoring_fixture_live():
        return _service_live_opt_in(service_name) if service_name else _any_live_opt_in()
    return True


def inactive_reason(profile_name: str, service_name: str | None = None) -> str | None:
    registry = _registry()
    policy = registry.get("policy") or {}
    if profile_name not in set(policy.get("enabled_profiles") or []):
        return "PROFILE_DISABLED"
    if policy.get("disable_when_current_scoring_fixture_live") is True and _current_scoring_fixture_live():
        eligible = _service_live_opt_in(service_name) if service_name else _any_live_opt_in()
        if eligible:
            return None
        if service_name is None:
            return "CURRENT_SCORING_FIXTURE_LIVE"
        return "CURRENT_SCORING_FIXTURE_LIVE_SERVICE_NOT_OPTED_IN"
    return None


def _normalize(value: Any, *, top_level: bool = False) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value):
            if key in _VOLATILE_KEYS:
                continue
            if top_level and key in {"endpoint_health"}:
                continue
            out[str(key)] = _normalize(value[key])
        return out
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _pick(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields}


def _prediction_official_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    bootstrap = value.get("bootstrap") if isinstance(value.get("bootstrap"), dict) else {}
    phase = value.get("phase") if isinstance(value.get("phase"), dict) else {}
    teams = [_pick(row, _PREDICTION_TEAM_FIELDS) for row in bootstrap.get("teams") or [] if isinstance(row, dict)]
    elements = [_pick(row, _PREDICTION_PLAYER_FIELDS) for row in bootstrap.get("elements") or [] if isinstance(row, dict)]
    fixtures = [_pick(row, _PREDICTION_FIXTURE_FIELDS) for row in value.get("fixtures") or [] if isinstance(row, dict)]
    teams.sort(key=lambda row: int(row.get("id") or 0))
    elements.sort(key=lambda row: int(row.get("id") or 0))
    fixtures.sort(key=lambda row: (
        int(row.get("event") or 999),
        str(row.get("kickoff_time") or ""),
        int(row.get("team_h") or 0),
        int(row.get("team_a") or 0),
    ))
    return {
        "planning_gw": phase.get("planning_gw"),
        "teams": teams,
        "elements": elements,
        "fixtures": fixtures,
    }


def _prediction_team_state(value: dict[str, Any]) -> dict[str, Any]:
    """Exact subset consumed by build_package_optimizer().

    Entry rank/event points/fetch timestamps and other presentation state are deliberately
    excluded because prediction_service never reads them. Any owned element, sell value,
    or ITB change remains material and invalidates reuse.
    """
    ledger = []
    for row in value.get("team_value_ledger") or []:
        if not isinstance(row, dict):
            continue
        ledger.append({
            "element": row.get("element"),
            "sell_cost": row.get("sell_cost"),
        })
    ledger.sort(key=lambda row: int(row.get("element") or 0))
    totals = value.get("totals") if isinstance(value.get("totals"), dict) else {}
    return {
        "team_value_ledger": ledger,
        "itb": totals.get("itb"),
    }


def _semantic_json(service_name: str, name: str, value: Any) -> Any:
    value = _normalize(value, top_level=True)
    if service_name == "prediction" and name == "official_snapshot.json" and isinstance(value, dict):
        return _prediction_official_snapshot(value)
    if service_name == "prediction" and name == "team.json" and isinstance(value, dict):
        return _prediction_team_state(value)
    return value


def _semantic_profile(service_name: str, name: str, suffix: str) -> str:
    if suffix != ".json":
        return "RAW"
    if service_name == "prediction" and name == "official_snapshot.json":
        return "PREDICTION_OFFICIAL_SNAPSHOT"
    if service_name == "prediction" and name == "team.json":
        return "PREDICTION_TEAM_STATE"
    return "GENERIC_JSON"


def _valid_hex_digest(value: str, lengths: tuple[int, ...]) -> bool:
    return len(value) in lengths and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _deployment_code_digest() -> tuple[str | None, str]:
    explicit = os.getenv("FPL_DEPLOYMENT_CODE_DIGEST", "").strip()
    if _valid_hex_digest(explicit, (64,)):
        return explicit.lower(), "FPL_DEPLOYMENT_CODE_DIGEST"

    github_sha = os.getenv("GITHUB_SHA", "").strip()
    if _valid_hex_digest(github_sha, (40, 64)):
        normalized = hashlib.sha256(f"git:{github_sha.lower()}".encode("utf-8")).hexdigest()
        return normalized, "GITHUB_SHA"
    return None, "SOURCE_TREE_HASH"


def source_tree_identity() -> dict[str, str | bool | None]:
    digest, source = _deployment_code_digest()
    return {
        "source": source,
        "digest_prefix": digest[:12] if digest else None,
        "precomputed": digest is not None,
    }


@lru_cache(maxsize=8)
def _digest_source_tree(path_text: str) -> str:
    path = Path(path_text)
    if path.resolve() == (ROOT / "src").resolve():
        deployment_digest, _ = _deployment_code_digest()
        if deployment_digest:
            return deployment_digest

    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*.py") if p.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _semantic_hash(value: Any, *, top_level: bool = False) -> str:
    """Canonical structural hash without rebuilding/serializing a normalized JSON copy."""
    digest = hashlib.sha256()

    def visit(item: Any, is_top: bool = False) -> None:
        if isinstance(item, dict):
            digest.update(b"{")
            for key in sorted(item, key=lambda value: str(value)):
                text = str(key)
                if text in _VOLATILE_KEYS:
                    continue
                if is_top and text == "endpoint_health":
                    continue
                digest.update(b"K")
                digest.update(text.encode("utf-8"))
                digest.update(b"\0")
                visit(item[key], False)
            digest.update(b"}")
            return
        if isinstance(item, list):
            digest.update(b"[")
            for value in item:
                visit(value, False)
            digest.update(b"]")
            return
        if item is None:
            digest.update(b"N")
        elif item is True:
            digest.update(b"T")
        elif item is False:
            digest.update(b"F")
        elif isinstance(item, str):
            digest.update(b"S")
            digest.update(item.encode("utf-8"))
            digest.update(b"\0")
        elif isinstance(item, int):
            digest.update(b"I")
            digest.update(str(item).encode("ascii"))
            digest.update(b"\0")
        elif isinstance(item, float):
            digest.update(b"R")
            digest.update(json.dumps(item, allow_nan=True, separators=(",", ":")).encode("ascii"))
            digest.update(b"\0")
        else:
            digest.update(b"J")
            digest.update(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))
            digest.update(b"\0")

    visit(value, top_level)
    return digest.hexdigest()


@lru_cache(maxsize=128)
def _digest_file_cached(profile: str, path_text: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    path = Path(path_text)
    if profile in {"GENERIC_JSON", "PREDICTION_OFFICIAL_SNAPSHOT", "PREDICTION_TEAM_STATE"}:
        value = read_json(path, None)
        if value is not None:
            if profile == "PREDICTION_OFFICIAL_SNAPSHOT" and isinstance(value, dict):
                value = _prediction_official_snapshot(value)
            elif profile == "PREDICTION_TEAM_STATE" and isinstance(value, dict):
                value = _prediction_team_state(value)
            return _semantic_hash(value, top_level=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_path(service_name: str, name: str) -> str | None:
    path = ROOT / name if name.startswith(("config/", "src/")) else DATA / name
    if path.is_dir():
        return _digest_source_tree(str(path.resolve()))
    if not path.is_file():
        return None
    stat = path.stat()
    profile = _semantic_profile(service_name, name, path.suffix)
    return _digest_file_cached(profile, str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def fingerprint(service_name: str) -> str | None:
    spec = (_registry().get("services") or {}).get(service_name)
    if not isinstance(spec, dict):
        return None
    rows: list[tuple[str, str]] = []
    for name in spec.get("inputs") or []:
        digest = _digest_path(service_name, str(name))
        if digest is None:
            return None
        rows.append((str(name), digest))
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stored_fingerprint(service_name: str) -> str | None:
    state = read_json(STATE_PATH, {})
    row = (state.get("services") or {}).get(service_name) if isinstance(state, dict) else None
    return str(row.get("fingerprint")) if isinstance(row, dict) and row.get("fingerprint") else None


def diagnose(service_name: str, profile_name: str | None = None) -> dict[str, Any]:
    if profile_name is not None and not active(profile_name, service_name):
        return {"reason": inactive_reason(profile_name, service_name), "current": None, "stored": None, "match": False}
    current = fingerprint(service_name)
    stored = stored_fingerprint(service_name)
    if current is None:
        reason = "MATERIAL_INPUT_MISSING"
    elif stored is None:
        reason = "NO_STORED_FINGERPRINT"
    elif current != stored:
        reason = "INPUT_FINGERPRINT_CHANGED"
    else:
        reason = "MATCH"
    return {
        "reason": reason,
        "current": current[:12] if current else None,
        "stored": stored[:12] if stored else None,
        "match": bool(current and stored and current == stored),
    }


def try_reuse(service_name: str, service_spec: dict[str, Any], profile_name: str) -> dict[str, Any] | None:
    registry = _registry()
    if not active(profile_name, service_name):
        return None
    if service_name not in (registry.get("services") or {}):
        return None
    artifacts = [str(name) for name in service_spec.get("artifacts") or []]
    if not artifacts:
        return None
    paths = [DATA / name for name in artifacts]
    if not all(path.is_file() for path in paths):
        return None
    current = fingerprint(service_name)
    if not current or stored_fingerprint(service_name) != current:
        return None
    validations = [validate_artifact(path, name) for path, name in zip(paths, artifacts)]
    return {
        "service": service_name,
        "status": "REUSED",
        "isolated": False,
        "data_dir": str(DATA),
        "elapsed_ms": 0.0,
        "queue_wait_ms": 0.0,
        "seed_input_ms": 0.0,
        "seed_input_bytes": 0,
        "validation_ms": 0.0,
        "promotion_ms": 0.0,
        "promoted_output_bytes": 0,
        "reuse_mode": "CONTENT_ADDRESSED",
        "input_fingerprint": current,
        "artifact_validation": validations,
        "commands": [],
    }


def record(service_name: str, profile_name: str, fingerprint_value: str | None = None) -> None:
    registry = _registry()
    if not active(profile_name, service_name):
        return
    if service_name not in (registry.get("services") or {}):
        return
    current = fingerprint_value or fingerprint(service_name)
    if not current:
        return
    state = read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["schema_version"] = 1
    state["registry"] = "V3_INCREMENTAL_REUSE_STATE_V1"
    state.setdefault("services", {})[service_name] = {"fingerprint": current}
    atomic_json(STATE_PATH, state)