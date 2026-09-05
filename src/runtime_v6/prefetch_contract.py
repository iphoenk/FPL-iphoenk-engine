from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .security import assert_publish_safe

SCHEMA_VERSION = 1
NORMALIZATION_VERSION = "v6-report-prefetch-1"
DEFAULT_CONFIG = Path("config/v6/consumer_context.json")
DEFAULT_OUTPUT = Path("data/v6")
PRICE_REPORT = "05:30_price"
REPORT_KINDS = frozenset({"full_master", "match_mode", "deadline_review", "ad_hoc", PRICE_REPORT})


class PrefetchContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReportScope:
    personal: bool
    mini_league: bool
    live: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict[str, Any], *, secrets: Iterable[str] = ()) -> None:
    assert_publish_safe(value, secret_values=tuple(secrets))
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(path)


def artifact_meta(output_root: Path, relative_path: str) -> dict[str, Any]:
    raw = (output_root / relative_path).read_bytes()
    return {
        "path": f"data/v6/{relative_path}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def parse_slot(value: str) -> datetime:
    try:
        slot = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PrefetchContractError("logical report slot must be ISO-8601") from exc
    if slot.tzinfo is None or slot.utcoffset() is None:
        raise PrefetchContractError("logical report slot must include an explicit timezone offset")
    return slot


def _priority_override(raw: str) -> list[dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        value = json.loads(raw)
        if not isinstance(value, list):
            raise PrefetchContractError("FPL_PRIORITY_LEAGUES JSON must be a list")
        return [dict(item) for item in value]
    priorities = []
    for token in filter(None, (part.strip() for part in raw.split(";"))):
        kind, name = token.split(":", 1) if ":" in token else ("classic", token)
        priorities.append(
            {"name": name.strip(), "kind": kind.strip(), "full_submitted_picks": True}
        )
    return priorities


def load_consumer_context(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise PrefetchContractError("V6 consumer context must be an object")
    config = dict(config)
    if os.getenv("FPL_TEAM_ID"):
        config["entry_id"] = int(os.environ["FPL_TEAM_ID"])
    if os.getenv("FPL_PRIORITY_LEAGUES"):
        config["priority_leagues"] = _priority_override(os.environ["FPL_PRIORITY_LEAGUES"])
    required = {
        "schema_version", "entry_id", "priority_leagues", "personal_team_enabled",
        "mini_league_enabled", "prefetch_lead_minutes", "prefetch_max_age_minutes",
    }
    missing = sorted(required - set(config))
    if missing:
        raise PrefetchContractError(f"V6 consumer context missing keys: {missing}")
    if int(config["entry_id"]) <= 0:
        raise PrefetchContractError("entry_id must be positive")
    return config


def resolve_scope(
    report_kind: str,
    config: dict[str, Any],
    *,
    ad_hoc_personal: bool = False,
    ad_hoc_mini_league: bool = False,
    ad_hoc_live: bool = False,
) -> ReportScope:
    if report_kind not in REPORT_KINDS:
        raise PrefetchContractError(f"unsupported report_kind={report_kind}")
    if report_kind == PRICE_REPORT:
        return ReportScope(False, False, False)
    personal = bool(config.get("personal_team_enabled", True))
    mini = bool(config.get("mini_league_enabled", True))
    if report_kind == "full_master":
        return ReportScope(personal, mini, False)
    if report_kind == "match_mode":
        return ReportScope(personal, mini, True)
    if report_kind == "deadline_review":
        return ReportScope(personal, mini and bool(config.get("deadline_review_mini_league_enabled")), False)
    return ReportScope(personal and ad_hoc_personal, mini and ad_hoc_mini_league, ad_hoc_live)


def select_gw(bootstrap: dict[str, Any], now: datetime) -> tuple[int | None, bool | None, str | None]:
    events = bootstrap.get("events")
    if not isinstance(events, list):
        return None, None, None
    event = next((item for item in events if item.get("is_current") is True), None)
    if event is None:
        eligible = []
        for item in events:
            raw = item.get("deadline_time")
            if not raw:
                continue
            try:
                deadline = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if deadline <= now.astimezone(timezone.utc):
                eligible.append((deadline, item))
        event = max(eligible, key=lambda pair: pair[0])[1] if eligible else next(
            (item for item in events if item.get("is_next") is True), None
        )
    if not event:
        return None, None, None
    gw = int(event["id"])
    raw = event.get("deadline_time")
    if not raw:
        return gw, None, None
    deadline = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return gw, now.astimezone(timezone.utc) >= deadline, deadline.isoformat()


def bootstrap_index(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    teams = {
        int(team["id"]): str(team.get("short_name") or team.get("name") or team["id"])
        for team in payload.get("teams", [])
        if isinstance(team, dict) and team.get("id") is not None
    }
    positions = {
        int(kind["id"]): str(kind.get("singular_name_short") or kind["id"])
        for kind in payload.get("element_types", [])
        if isinstance(kind, dict) and kind.get("id") is not None
    }
    elements = {}
    for item in payload.get("elements", []):
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        element_id = int(item["id"])
        elements[element_id] = {
            "element_id": element_id,
            "web_name": item.get("web_name"),
            "club": teams.get(int(item["team"])) if item.get("team") is not None else None,
            "position": positions.get(int(item["element_type"])) if item.get("element_type") is not None else None,
            "current_price": item.get("now_cost"),
        }
    return elements


def lineage(
    result: dict[str, Any] | None,
    *,
    origin: str = "LIVE_FETCHED",
    gw: int | None = None,
    entry_id: int | None = None,
    league_id: int | None = None,
    pagination_coverage: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "authority": "OFFICIAL_FPL",
        "endpoint_class": result.get("endpoint_class"),
        "checked_at": result.get("checked_at"),
        "http_status": result.get("http_status"),
        "payload_digest": result.get("payload_digest"),
        "origin": origin,
        "gw": gw,
        "entry_id": entry_id,
        "league_id": league_id,
        "pagination_coverage": pagination_coverage,
        "normalization_version": NORMALIZATION_VERSION,
    }


def freshness(generated: datetime, slot: datetime, maximum_age_minutes: int) -> tuple[float, bool]:
    age = max(0.0, (slot.astimezone(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 60)
    return round(age, 3), age <= maximum_age_minutes


def reusable(
    previous: dict[str, Any] | None,
    *,
    slot_identity: str,
    logical_slot: datetime,
    now: datetime,
    maximum_age_minutes: int,
) -> bool:
    if not previous or previous.get("slot_identity") != slot_identity or previous.get("complete") is not True:
        return False
    try:
        generated = datetime.fromisoformat(str(previous["generated_at"]))
    except (KeyError, ValueError):
        return False
    _, is_fresh = freshness(generated, logical_slot, maximum_age_minutes)
    return is_fresh and generated <= now.astimezone(timezone.utc)
