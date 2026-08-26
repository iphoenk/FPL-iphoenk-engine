from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_phase_authority_registry.json"


class Phase(str, Enum):
    PRE_DEADLINE = "PRE_DEADLINE"
    POST_DEADLINE = "POST_DEADLINE"
    LIVE = "LIVE"
    POST_GW = "POST_GW"


def _registry() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("phases"), dict):
        raise RuntimeError("invalid V5 phase authority registry")
    return data


def _as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_phase(
    *,
    deadline_time: datetime | str | None,
    now: datetime | str | None = None,
    live_started: bool = False,
    finished: bool = False,
) -> Phase:
    if finished:
        return Phase.POST_GW
    if live_started:
        return Phase.LIVE
    deadline = _as_utc(deadline_time)
    current = _as_utc(now) or datetime.now(timezone.utc)
    if deadline is None or current < deadline:
        return Phase.PRE_DEADLINE
    return Phase.POST_DEADLINE


def authority_chain(phase: Phase | str, domain: str) -> tuple[str, ...]:
    phase_name = Phase(str(phase)).value if not isinstance(phase, Phase) else phase.value
    raw = _registry()["phases"].get(phase_name)
    if not isinstance(raw, dict):
        raise KeyError(f"unknown V5 phase: {phase_name}")
    chain = raw.get(domain)
    if not isinstance(chain, list):
        raise KeyError(f"unknown V5 phase domain: {phase_name}.{domain}")
    return tuple(str(x) for x in chain)


def primary_authority(phase: Phase | str, domain: str) -> str:
    chain = authority_chain(phase, domain)
    if not chain:
        raise RuntimeError(f"empty V5 authority chain: {phase}.{domain}")
    return chain[0]


def reconciliation_policy() -> dict[str, Any]:
    raw = _registry().get("reconciliation")
    return dict(raw) if isinstance(raw, dict) else {}
