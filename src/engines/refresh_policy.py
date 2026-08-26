from __future__ import annotations

from datetime import datetime

from src.engines.checkpoint_policy import resolve_checkpoint


def refresh_interval_minutes(
    deadline: str | None,
    is_live: bool = False,
    as_of: datetime | str | None = None,
    run_mode: str = "daily",
) -> int:
    context = resolve_checkpoint(run_mode, deadline, is_live=is_live, as_of=as_of)
    return int(context["recommended_refresh_minutes"])


def mode(
    deadline: str | None,
    is_live: bool = False,
    as_of: datetime | str | None = None,
    run_mode: str = "daily",
) -> dict:
    context = resolve_checkpoint(run_mode, deadline, is_live=is_live, as_of=as_of)
    minutes = int(context["recommended_refresh_minutes"])
    return {
        "mode": context["policy_id"],
        "recommended_interval_minutes": minutes,
        "requires_always_on_host": minutes < 15 or is_live,
        "checkpoint_context": context,
    }
