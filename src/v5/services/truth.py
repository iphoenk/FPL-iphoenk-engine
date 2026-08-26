from __future__ import annotations

from typing import Any

from src.v5.event_context import build_event_context
from src.v5.identity import build_index, resolve_many
from src.v5.live_scoring import personalized_live_score
from src.v5.team_service import build_team_state
from src.v5.services.common import context_dict, locked_squad, parse_datetime


def handle(operation: str, payload: dict[str, Any]) -> Any:
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("truth service requires bootstrap")

    if operation == "context":
        return context_dict(build_event_context(bootstrap, now=parse_datetime(payload.get("now"))))

    identity = build_index(bootstrap)
    if operation == "resolve":
        return list(resolve_many(payload.get("element_ids") or (), identity))
    if operation != "assemble":
        raise KeyError(f"unsupported truth operation: {operation}")

    context = build_event_context(bootstrap, now=parse_datetime(payload.get("now")))
    auth_runtime = payload.get("auth_runtime") if isinstance(payload.get("auth_runtime"), dict) else {}
    dynamic = payload.get("dynamic") if isinstance(payload.get("dynamic"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    team = build_team_state(
        phase=context.phase,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=payload.get("locked_squad") if isinstance(payload.get("locked_squad"), dict) else locked_squad(),
        authenticated_my_team=auth_runtime.get("my_team") if isinstance(auth_runtime.get("my_team"), dict) else None,
        submitted_picks=dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None,
        transfers=base.get("entry_transfers") if isinstance(base.get("entry_transfers"), list) else [],
        entry=base.get("entry") if isinstance(base.get("entry"), dict) else None,
    )
    live = personalized_live_score(
        picks=dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None,
        event_live=dynamic.get("event_live") if isinstance(dynamic.get("event_live"), dict) else None,
        identity=identity,
        scoring_gw=context.scoring_gw,
        is_live_event=context.is_live_event,
    )
    return {"context": context_dict(context), "team": team, "live": live}
