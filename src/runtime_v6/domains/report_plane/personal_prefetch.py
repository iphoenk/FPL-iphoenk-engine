from __future__ import annotations

from typing import Any

from .prefetch_contract import NORMALIZATION_VERSION, SCHEMA_VERSION, iso, lineage, utc_now

SYSTEM_LEAGUE_TYPES = frozenset({"s"})
AUTH_STATES = {
    "AUTH_AVAILABLE",
    "AUTH_EXPIRED",
    "AUTH_INVALID",
    "AUTH_ENTRY_MISMATCH",
    "AUTH_UNAVAILABLE",
}


def discover_memberships(entry_payload: dict[str, Any], discovered_at: str) -> list[dict[str, Any]]:
    leagues = entry_payload.get("leagues") or {}
    memberships: list[dict[str, Any]] = []
    for kind in ("classic", "h2h"):
        for league in leagues.get(kind) or []:
            if not isinstance(league, dict) or league.get("id") is None:
                continue
            if str(league.get("league_type") or "").lower() in SYSTEM_LEAGUE_TYPES:
                continue
            memberships.append(
                {
                    "league_id": int(league["id"]),
                    "league_name": str(league.get("name") or ""),
                    "league_kind": kind,
                    "league_type": league.get("league_type"),
                    "current_rank": league.get("rank"),
                    "previous_rank": league.get("last_rank"),
                    "entry_can_leave": league.get("entry_can_leave"),
                    "entry_can_admin": league.get("entry_can_admin"),
                    "entry_can_invite": league.get("entry_can_invite"),
                    "discovered_at": discovered_at,
                }
            )
    return memberships


def resolve_priority_leagues(
    memberships: list[dict[str, Any]], configured: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    resolved = []
    for wanted in configured:
        name = str(wanted.get("name") or "").strip()
        kind = str(wanted.get("kind") or "classic").strip().lower()
        matches = [
            league
            for league in memberships
            if league["league_kind"] == kind
            and league["league_name"].strip().casefold() == name.casefold()
        ]
        base = {
            "league_name": name,
            "league_kind": kind,
            "full_submitted_picks": bool(wanted.get("full_submitted_picks")),
        }
        if len(matches) == 1:
            resolved.append({**matches[0], **base, "resolution_status": "RESOLVED"})
        elif not matches:
            resolved.append({**base, "league_id": None, "resolution_status": "NOT_FOUND", "candidate_league_ids": []})
        else:
            resolved.append(
                {
                    **base,
                    "league_id": None,
                    "resolution_status": "AMBIGUOUS",
                    "candidate_league_ids": sorted(int(item["league_id"]) for item in matches),
                }
            )
    return resolved


def normalise_submitted_picks(
    entry_id: int,
    gw: int | None,
    result: dict[str, Any] | None,
    *,
    origin: str = "LIVE_FETCHED_CURRENT_GW",
) -> dict[str, Any]:
    if gw is None or result is None or result.get("status") != "LIVE":
        return {
            "schema_version": SCHEMA_VERSION,
            "entry_id": entry_id,
            "gw": gw,
            "status": "UNAVAILABLE",
            "generated_at": iso(utc_now()),
            "active_chip": None,
            "entry_history": None,
            "automatic_subs": None,
            "picks": [],
            "lineage": lineage(result, origin=origin, gw=gw, entry_id=entry_id),
            "authority": "OFFICIAL_FPL",
            "normalization_version": NORMALIZATION_VERSION,
        }
    payload = result.get("payload") or {}
    picks = []
    for pick in payload.get("picks") or []:
        if not isinstance(pick, dict) or pick.get("element") is None:
            continue
        position = pick.get("position")
        picks.append(
            {
                "element_id": int(pick["element"]),
                "squad_position": position,
                "multiplier": pick.get("multiplier"),
                "captain": bool(pick.get("is_captain")),
                "vice_captain": bool(pick.get("is_vice_captain")),
                "bench_order": int(position) - 11 if isinstance(position, int) and position > 11 else None,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "entry_id": entry_id,
        "gw": gw,
        "status": "AVAILABLE",
        "generated_at": iso(utc_now()),
        "active_chip": payload.get("active_chip"),
        # Preserve the Official per-GW financial/scoring fields without
        # confusing them with authenticated pre-deadline team finance.
        "entry_history": dict(payload["entry_history"]) if isinstance(payload.get("entry_history"), dict) else None,
        "automatic_subs": list(payload["automatic_subs"]) if isinstance(payload.get("automatic_subs"), list) else None,
        "picks": picks,
        "lineage": lineage(result, origin=origin, gw=gw, entry_id=entry_id),
        "authority": "OFFICIAL_FPL",
        "normalization_version": NORMALIZATION_VERSION,
    }


def verified_auth_entry(me_payload: dict[str, Any]) -> int | None:
    player = me_payload.get("player")
    if isinstance(player, dict) and player.get("entry") is not None:
        return int(player["entry"])
    if me_payload.get("entry") is not None:
        return int(me_payload["entry"])
    return None


def _normalise_auth_state(raw_state: str, auth_lineage: list[dict[str, Any] | None]) -> str:
    raw = str(raw_state or "").upper()
    if raw in AUTH_STATES:
        return raw
    if raw == "AVAILABLE":
        return "AUTH_AVAILABLE"
    if raw == "AUTH_ENTRY_MISMATCH":
        return "AUTH_ENTRY_MISMATCH"
    if raw in {"AUTH_IDENTITY_UNVERIFIED", "AUTH_CONFIGURATION_INVALID", "INVALID"}:
        return "AUTH_INVALID"
    statuses = {
        int(item.get("http_status"))
        for item in auth_lineage
        if isinstance(item, dict) and isinstance(item.get("http_status"), int)
    }
    if 401 in statuses:
        return "AUTH_EXPIRED"
    if statuses.intersection({400, 403}):
        return "AUTH_INVALID"
    if raw in {"AUTH_UNAVAILABLE", "UNAVAILABLE", "DEGRADED", ""}:
        return "AUTH_UNAVAILABLE"
    return "AUTH_INVALID"


def normalise_authenticated_free_transfers(transfers: dict[str, Any] | None) -> tuple[int | None, str]:
    """Read remaining transfers only from authenticated Official FPL fields.

    FPL's `transfers.limit` is the allowance for this GW, while `made`
    counts transfers used in this GW. Never infer either from public picks,
    chips, previous GW, or the fixture calendar. Null limit means unlimited
    transfers (for example a chip), not an integer FT balance.
    """
    if not isinstance(transfers, dict):
        return None, "NOT_SUPPORTED"
    explicit = transfers.get("free_transfers")
    if type(explicit) is int and 0 <= explicit <= 5:
        return explicit, "OFFICIAL_EXPLICIT"
    if "limit" in transfers and transfers["limit"] is None:
        return None, "UNLIMITED"
    limit, made = transfers.get("limit"), transfers.get("made")
    if type(limit) is int and 0 <= limit <= 5 and type(made) is int and made >= 0:
        return max(0, limit - made), "AUTHENTICATED_LIMIT_MINUS_MADE"
    return None, "NOT_SUPPORTED"


def normalise_team(
    *,
    entry_id: int,
    gw: int | None,
    editable_planning_gw: int | None = None,
    element_index: dict[int, dict[str, Any]],
    bootstrap_lineage: dict[str, Any] | None,
    submitted: dict[str, Any],
    auth_state: str,
    my_team_payload: dict[str, Any] | None,
    auth_lineage: list[dict[str, Any] | None],
    generated_at: str,
) -> dict[str, Any]:
    authenticated_state = _normalise_auth_state(auth_state, auth_lineage)
    submitted_by_element = {
        int(item["element_id"]): item
        for item in submitted.get("picks", [])
        if item.get("element_id") is not None
    }
    auth_picks = (my_team_payload or {}).get("picks") if isinstance(my_team_payload, dict) else None
    source = auth_picks if isinstance(auth_picks, list) else submitted.get("picks", [])
    players = []
    for raw in source:
        if not isinstance(raw, dict):
            continue
        element = raw.get("element", raw.get("element_id"))
        if element is None:
            continue
        element_id = int(element)
        pick = submitted_by_element.get(element_id, {})
        meta = element_index.get(element_id, {})
        players.append(
            {
                "element_id": element_id,
                "position": meta.get("position"),
                "current_price": meta.get("current_price"),
                "purchase_price": raw.get("purchase_price") if "purchase_price" in raw else None,
                "selling_price": raw.get("selling_price") if "selling_price" in raw else None,
                "squad_position": pick.get("squad_position", raw.get("position")),
                "multiplier": pick.get("multiplier"),
                "captain": pick.get("captain"),
                "vice_captain": pick.get("vice_captain"),
                "bench_order": pick.get("bench_order"),
            }
        )

    transfers = (my_team_payload or {}).get("transfers") if isinstance(my_team_payload, dict) else None
    transfers = transfers if isinstance(transfers, dict) else {}
    free_transfers, free_transfers_source = (
        normalise_authenticated_free_transfers(transfers)
        if authenticated_state == "AUTH_AVAILABLE"
        else (None, "NOT_SUPPORTED")
    )

    raw_chips = (my_team_payload or {}).get("chips") if isinstance(my_team_payload, dict) else None
    chips = None
    if isinstance(raw_chips, list):
        chips = [
            {
                "name": chip.get("name"),
                "status_for_entry": chip.get("status_for_entry"),
                "played_by_entry": chip.get("played_by_entry"),
            }
            for chip in raw_chips
            if isinstance(chip, dict)
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "semantic_class": "NORMALIZED_FACT",
        "canonical": True,
        "entry_id": entry_id,
        "gw": gw,
        # gw is the last/current scoring event. This separate, Official
        # bootstrap-derived next event is the editable transfer horizon.
        "editable_planning_gw": (
            editable_planning_gw
            if authenticated_state == "AUTH_AVAILABLE"
            and isinstance(auth_picks, list)
            and isinstance(editable_planning_gw, int)
            and editable_planning_gw > 0
            else None
        ),
        "generated_at": generated_at,
        "authority": "OFFICIAL_FPL",
        "auth_state": authenticated_state,
        "squad_state": "AUTHENTICATED_CURRENT_TEAM"
        if authenticated_state == "AUTH_AVAILABLE" and isinstance(auth_picks, list)
        else "SUBMITTED_PICKS_ONLY",
        "bank": transfers.get("bank"),
        "free_transfers": free_transfers,
        "free_transfers_source": free_transfers_source,
        "transfers_made": transfers.get("made"),
        "hit_cost": transfers.get("cost"),
        "chips": chips,
        "players": players,
        "availability": {
            "authenticated_state": authenticated_state,
            "bank": "AVAILABLE" if "bank" in transfers else "UNAVAILABLE",
            "free_transfers": (
                "AVAILABLE" if free_transfers is not None
                else "UNLIMITED" if free_transfers_source == "UNLIMITED"
                else "NOT_SUPPORTED"
            ),
            "purchase_price": "AVAILABLE"
            if players and all(item["purchase_price"] is not None for item in players)
            else "UNAVAILABLE",
            "selling_price": "AVAILABLE"
            if players and all(item["selling_price"] is not None for item in players)
            else "UNAVAILABLE",
            "chips": "AVAILABLE" if chips is not None else "UNAVAILABLE",
        },
        "lineage": {
            "bootstrap_static": bootstrap_lineage,
            "submitted_picks": submitted.get("lineage"),
            "authenticated": [item for item in auth_lineage if item is not None],
            "normalization_version": NORMALIZATION_VERSION,
        },
        "governance": {
            "data_only": True,
            "auth_bypass_used": False,
            "finance_is_upstream_fact_only": True,
            "free_transfers_are_not_derived": free_transfers_source != "AUTHENTICATED_LIMIT_MINUS_MADE",
            "free_transfers_from_authenticated_limit_made_only": (
                free_transfers_source == "AUTHENTICATED_LIMIT_MINUS_MADE"
            ),
            "squad_value_aggregates_not_authored": True,
        },
    }
