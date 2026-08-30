from __future__ import annotations

from typing import Any

from src.v5.authenticated_official import safe_finance
from src.v5.finance import build_squad_ledger
from src.v5.identity import ElementIndex
from src.v5.squad import select_squad


def _initial_purchase_costs(lock: dict | None) -> dict[int, int]:
    out = {}
    for row in (lock or {}).get("players", []) or []:
        if row.get("element") is None or row.get("purchase_cost") is None:
            continue
        out[int(row["element"])] = int(row["purchase_cost"])
    return out


def _now_costs(index: ElementIndex) -> dict[int, int]:
    return {
        int(eid): int(player["now_cost"])
        for eid, player in index.players.items()
        if player.get("now_cost") is not None
    }


def build_team_state(
    *,
    phase,
    bootstrap: dict,
    identity: ElementIndex,
    locked_squad: dict | None,
    authenticated_my_team: dict | None,
    submitted_picks: dict | None,
    transfers: list[dict] | None,
    entry: dict | None,
    planning_gw: int | None = None,
    submitted_gw: int | None = None,
) -> dict[str, Any]:
    resolved = select_squad(
        phase=phase,
        bootstrap=bootstrap,
        locked_squad=locked_squad,
        authenticated_my_team=authenticated_my_team,
        submitted_picks=submitted_picks,
        planning_gw=planning_gw,
        submitted_gw=submitted_gw,
    )
    squad = tuple(resolved["squad"])
    owned_ids = tuple(int(row["element"]) for row in squad)
    auth_finance = safe_finance(authenticated_my_team, owned_ids) if authenticated_my_team else {
        "bank": None,
        "coverage": {"expected": len(owned_ids), "covered": 0, "complete": False},
        "prices_for_authoritative_squad": [],
    }
    ledger = build_squad_ledger(
        squad,
        now_costs=_now_costs(identity),
        transfers=transfers or [],
        authenticated_prices=auth_finance.get("prices_for_authoritative_squad", []),
        initial_purchase_costs=_initial_purchase_costs(locked_squad),
    )
    bank = auth_finance.get("bank")
    if bank is None and resolved["authority"] == "user_capture" and locked_squad:
        bank = locked_squad.get("itb_tenths")
    if bank is None and isinstance(entry, dict):
        bank = entry.get("last_deadline_bank")
    return {
        "authority": resolved["authority"],
        "authority_policy": resolved.get("authority_policy", {}),
        "squad": list(squad),
        "validation": resolved["validation"],
        "finance": {
            **ledger,
            "bank": bank,
            "authenticated_coverage": auth_finance.get("coverage", {}),
            "authenticated_role": "OPTIONAL_PRIVATE_ENRICHMENT",
        },
        "owned_ids": list(owned_ids),
    }
