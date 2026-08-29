from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.runtime_v3.artifact_contracts import validate_artifact
from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "runtime" / "incremental_reuse.json"
STATE_PATH = DATA / "incremental_reuse_state.json"

_VOLATILE_KEYS = {"generated_at", "runtime_architecture"}
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


def _semantic_json(service_name: str, name: str, value: Any) -> Any:
    value = _normalize(value, top_level=True)
    if service_name == "prediction" and name == "official_snapshot.json" and isinstance(value, dict):
        return _prediction_official_snapshot(value)
    return value


@lru_cache(maxsize=8)
def _digest_source_tree(path_text: str) -> str:
    path = Path(path_text)
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*.py") if p.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _digest_path(service_name: str, name: str) -> str | None:
    path = ROOT / name if name.startswith(("config/", "src/")) else DATA / name
    if path.is_dir():
        return _digest_source_tree(str(path.resolve()))
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if path.suffix == ".json":
        try:
            value = json.loads(raw.decode("utf-8"))
            raw = json.dumps(
                _semantic_json(service_name, name, value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except Exception:
            pass
    return hashlib.sha256(raw).hexdigest()


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
