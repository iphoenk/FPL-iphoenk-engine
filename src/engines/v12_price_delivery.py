from __future__ import annotations

"""V12 PRICE delivery barrier.

Downstream report-plane only. It consumes V6 facts and existing V12 model
outputs, materializes the Canonical PRICE surface, and validates the actual
visible body. It does not acquire/publish V6 data, create a scheduler, predict
prices, mutate ownership, or infer a contemplated transfer as executed.
"""

from collections import Counter
from datetime import datetime
import re
from typing import Any, Mapping, Sequence
import hashlib
import json
from pathlib import Path

from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_price_presentation_lock import (
    load_price_presentation_lock,
    validate_price_presentation_lock,
)
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_price20,
    build_watchlist20,
)


PRICE_SECTION_IDS = tuple(f"PRICE{index}" for index in range(1, 13))
ACTION_BOARD_FIELDS = (
    "NOW",
    "NEXT",
    "TRIGGER TO ACT",
    "LATEST SAFE DECISION POINT",
    "COST OF WAITING",
    "ABORT / REVERSAL",
)
ACTIONS = frozenset({"WAIT", "PREPARE", "ACT"})
POSITION_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CURRENT_AUTH_STATES = frozenset({"AVAILABLE", "AUTH_AVAILABLE", "CURRENT", "PASS"})
CURRENT_SQUAD_STATES = frozenset({"AUTHENTICATED_CURRENT_TEAM", "CURRENT_TEAM", "CURRENT"})


class PriceDeliveryError(ValueError):
    pass


def _aware(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _position(value: Any) -> str:
    text = str(value or "").upper()
    return "GK" if text in {"GK", "GKP", "1"} else (
        POSITION_BY_TYPE.get(int(value), text)
        if str(value or "").isdigit()
        else text
    )


def _player_map(bootstrap: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["id"]): dict(row)
        for row in bootstrap.get("elements") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }


def _normalise_team_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    players = _player_map(bootstrap)
    output: list[dict[str, Any]] = []
    for row in rows:
        element = row.get("element_id", row.get("element"))
        if element is None:
            continue
        try:
            element_id = int(element)
        except (TypeError, ValueError):
            continue
        official = players.get(element_id) or {}
        output.append(
            {
                "element_id": element_id,
                "element": element_id,
                "name": row.get("name")
                or row.get("display_name")
                or official.get("web_name")
                or str(element_id),
                "position": _position(
                    row.get("position")
                    or row.get("element_type")
                    or official.get("element_type")
                ),
                "team_id": int(row.get("team_id") or official.get("team") or 0),
                "now_cost": int(
                    row.get("current_price")
                    or row.get("now_cost")
                    or official.get("now_cost")
                    or 0
                ),
                "current_price": row.get("current_price")
                or official.get("now_cost"),
                "sell_value": row.get("authenticated_sell_value", row.get("sell_value")),
                "purchase_price": row.get("purchase_price"),
                "squad_position": row.get("squad_position"),
                "bench_order": row.get("bench_order"),
                "captain": bool(row.get("captain")),
                "vice_captain": bool(row.get("vice_captain")),
                "eligible": True,
            }
        )
    return output


def _state_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    confirmed = dict(state.get("confirmed_current_squad_state") or {})
    rows: list[dict[str, Any]] = []
    for key, position in (
        ("goalkeepers", "GK"),
        ("defenders", "DEF"),
        ("midfielders", "MID"),
        ("forwards", "FWD"),
    ):
        for raw in confirmed.get(key) or []:
            if isinstance(raw, Mapping):
                row = dict(raw)
                row["position"] = position
                rows.append(row)
    return rows


def _candidate(
    *,
    source_class: str,
    rows: Sequence[Mapping[str, Any]],
    bootstrap: Mapping[str, Any],
    gw: Any,
    observed_at: Any,
    authoritative_current: bool,
    finance: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalised = _normalise_team_rows(rows, bootstrap=bootstrap)
    ids = [int(row["element_id"]) for row in normalised]
    if len(normalised) != 15 or len(set(ids)) != 15:
        return None
    try:
        applicable_gw = int(gw) if gw is not None else None
    except (TypeError, ValueError):
        applicable_gw = None
    return {
        "source_class": source_class,
        "rows": normalised,
        "gw": applicable_gw,
        "observed_at": str(observed_at or ""),
        "observed_dt": _aware(observed_at),
        "authoritative_current": bool(authoritative_current),
        "finance": dict(finance or {}),
    }


def resolve_current15(
    *,
    planning_gw: int,
    bootstrap: Mapping[str, Any],
    explicit_user_evidence: Mapping[str, Any] | None = None,
    authenticated_current_team: Mapping[str, Any] | None = None,
    personal_artifact: Mapping[str, Any] | None = None,
    last_good_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve occurrence-bound CURRENT15 without pinning any player identity.

    Current-GW evidence competes by evidence time. Explicit user evidence is
    authoritative for its stated GW but can be superseded by newer authenticated
    current-GW Official evidence. Previous-GW/unspecified evidence is only a
    visibly STALE last-good fallback.
    """
    candidates: list[dict[str, Any]] = []

    explicit = dict(explicit_user_evidence or {})
    explicit_rows = explicit.get("players") or explicit.get("rows") or []
    if explicit_rows:
        row = _candidate(
            source_class="USER_EXPLICIT_CURRENT_GW",
            rows=explicit_rows,
            bootstrap=bootstrap,
            gw=explicit.get("gw"),
            observed_at=explicit.get("observed_at") or explicit.get("generated_at"),
            authoritative_current=True,
            finance=explicit.get("finance"),
        )
        if row:
            candidates.append(row)

    for source_class, payload in (
        ("AUTHENTICATED_OFFICIAL_CURRENT_TEAM", dict(authenticated_current_team or {})),
        ("AUTHENTICATED_PERSONAL_ARTIFACT", dict(personal_artifact or {})),
    ):
        rows = payload.get("players") or payload.get("rows") or []
        auth_state = str(payload.get("auth_state") or payload.get("availability_state") or "").upper()
        squad_state = str(payload.get("squad_state") or "").upper()
        current_auth = bool(
            auth_state in CURRENT_AUTH_STATES
            and (not squad_state or squad_state in CURRENT_SQUAD_STATES)
        )
        if rows:
            row = _candidate(
                source_class=source_class,
                rows=rows,
                bootstrap=bootstrap,
                gw=payload.get("gw"),
                observed_at=payload.get("generated_at") or payload.get("observed_at"),
                authoritative_current=current_auth,
                finance={
                    "bank": payload.get("bank"),
                    "free_transfers": payload.get("free_transfers"),
                    "hit_cost": payload.get("hit_cost"),
                    "transfers_made": payload.get("transfers_made"),
                },
            )
            if row:
                candidates.append(row)

    fallback = dict(last_good_evidence or {})
    fallback_rows = fallback.get("players") or fallback.get("rows") or fallback.get("picks") or []
    if fallback_rows:
        mapped_rows = []
        for raw in fallback_rows:
            if not isinstance(raw, Mapping):
                continue
            mapped = dict(raw)
            if "element_id" not in mapped and mapped.get("element") is not None:
                mapped["element_id"] = mapped.get("element")
            mapped_rows.append(mapped)
        row = _candidate(
            source_class="LAST_GOOD_CURRENT15",
            rows=mapped_rows,
            bootstrap=bootstrap,
            gw=fallback.get("gw"),
            observed_at=fallback.get("generated_at") or fallback.get("observed_at"),
            authoritative_current=False,
            finance=fallback.get("finance"),
        )
        if row:
            candidates.append(row)

    current = [
        row
        for row in candidates
        if row["gw"] == int(planning_gw) and row["authoritative_current"]
    ]
    if current:
        priority = {
            "USER_EXPLICIT_CURRENT_GW": 2,
            "AUTHENTICATED_OFFICIAL_CURRENT_TEAM": 1,
            "AUTHENTICATED_PERSONAL_ARTIFACT": 0,
        }
        chosen = max(
            current,
            key=lambda row: (
                row["observed_dt"] or datetime.min.replace(tzinfo=_aware("1970-01-01T00:00:00+00:00").tzinfo),
                priority.get(row["source_class"], -1),
            ),
        )
        return {
            "state": "CURRENT",
            "supportable": True,
            "rows": chosen["rows"],
            "element_ids": [row["element_id"] for row in chosen["rows"]],
            "source_class": chosen["source_class"],
            "gw": chosen["gw"],
            "observed_at": chosen["observed_at"] or "UNAVAILABLE",
            "finance": chosen["finance"],
            "reason": None,
        }

    if candidates:
        chosen = max(
            candidates,
            key=lambda row: row["observed_dt"]
            or datetime.min.replace(tzinfo=_aware("1970-01-01T00:00:00+00:00").tzinfo),
        )
        return {
            "state": "STALE",
            "supportable": False,
            "rows": chosen["rows"],
            "element_ids": [row["element_id"] for row in chosen["rows"]],
            "source_class": chosen["source_class"],
            "gw": chosen["gw"],
            "observed_at": chosen["observed_at"] or "UNAVAILABLE",
            "finance": chosen["finance"],
            "reason": "no authoritative CURRENT15 evidence explicitly applicable to current planning GW",
        }

    return {
        "state": "UNRESOLVED",
        "supportable": False,
        "rows": [],
        "element_ids": [],
        "source_class": None,
        "gw": None,
        "observed_at": "UNAVAILABLE",
        "finance": {},
        "reason": "no valid 15-player ownership evidence available",
    }


def explicit_user_evidence_from_state(state: Mapping[str, Any]) -> dict[str, Any] | None:
    confirmed = dict(state.get("confirmed_current_squad_state") or {})
    personal = dict(confirmed.get("current_personal_state") or {})
    source = str(state.get("source") or confirmed.get("status") or "").upper()
    if "USER_EXPLICIT" not in source and "SCREENSHOT" not in source:
        return None
    rows = _state_rows(state)
    if not rows:
        return None
    return {
        "players": rows,
        "gw": personal.get("gw"),
        "observed_at": personal.get("screenshot_observed_at")
        or state.get("updated_at"),
        "finance": {
            "bank": (
                float(personal["bank_gbp_m"]) * 10
                if personal.get("bank_gbp_m") is not None
                else None
            ),
            "free_transfers": personal.get("free_transfers"),
            "hit_cost": personal.get("transfer_cost_points"),
        },
    }


def _eta_status(row: Mapping[str, Any]) -> str:
    if row.get("estimated_change_date_wib"):
        return "MODEL " + str(row["estimated_change_date_wib"])
    state = str(row.get("date_state") or "").upper()
    if state == "EXPECTED_CHANGE_DATE":
        return "MODEL NEXT PRICE CYCLE"
    if state == "NO_CROSSING_WITHIN_GOVERNED_HORIZON":
        return "NO RELIABLE ETA"
    if row.get("next_official_price_cycle_wib"):
        return "NEXT PRICE CYCLE"
    return "UNAVAILABLE"


def _price_map(predictor_artifact: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    data = dict(predictor_artifact.get("data") or {})
    rows = data.get("players") or predictor_artifact.get("players") or []
    return {
        int(row["id"]): row
        for row in rows
        if isinstance(row, Mapping) and row.get("id") is not None
    }


def _strict_directional_price20(
    *,
    predictor_artifact: Mapping[str, Any] | None,
    direction: str,
    owned_element_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Apply PRICE exact20 direction semantics to the existing predictor materializer."""
    block = build_price20(
        predictor_artifact=predictor_artifact,
        direction=direction,
        owned_element_ids=owned_element_ids,
    )
    wanted = str(direction or "").upper()
    rows = [
        dict(row)
        for row in block.get("rows") or []
        if str(row.get("direction") or "").upper() == wanted
    ]
    if len(rows) == 20 and str(block.get("state") or "").upper() == "COMPLETE":
        return {**block, "rows": rows, "available_count": 20}
    reason = block.get("degradation_reason")
    if len(rows) < 20:
        direction_reason = (
            f"only {len(rows)} valid {wanted} rows available from the governed "
            "full-universe predictor materialization"
        )
        reason = f"{reason}; {direction_reason}" if reason else direction_reason
    return {
        **block,
        "state": "DEGRADED" if rows else "UNAVAILABLE",
        "rows": rows,
        "available_count": len(rows),
        "expected_count": 20,
        "degradation_reason": reason or f"{wanted} exact20 unavailable",
    }


def _load_priority_mini_league(
    runtime_data_root: Path,
) -> dict[str, Any]:
    """Resolve the occurrence mini-league from runtime membership evidence, never a fixed ID."""
    memberships = _read_json(
        runtime_data_root / "data/v6/personal/memberships.json", {}
    ) or {}
    priority = [
        dict(row)
        for row in memberships.get("priority_resolution") or []
        if isinstance(row, Mapping)
        and row.get("league_id") is not None
        and str(row.get("resolution_status") or "").upper() in {"RESOLVED", "AVAILABLE", "CURRENT"}
    ]
    candidates: list[tuple[datetime | None, int, dict[str, Any]]] = []

    for membership in priority:
        league_id = int(membership["league_id"])
        path = (
            runtime_data_root
            / "data/v6/mini_leagues"
            / str(league_id)
            / "standings.json"
        )
        payload = _read_json(path, {}) or {}
        if payload:
            enriched = dict(payload)
            enriched.setdefault("league_id", league_id)
            enriched.setdefault("league_name", membership.get("league_name"))
            enriched["membership_resolution"] = "PRIORITY_RESOLUTION"
            generated = _aware(payload.get("generated_at"))
            candidates.append((generated, league_id, enriched))

    if not candidates:
        root = runtime_data_root / "data/v6/mini_leagues"
        if root.exists():
            for path in root.glob("*/standings.json"):
                payload = _read_json(path, {}) or {}
                if not payload or not payload.get("user_summary"):
                    continue
                try:
                    league_id = int(path.parent.name)
                except ValueError:
                    continue
                enriched = dict(payload)
                enriched.setdefault("league_id", league_id)
                enriched["membership_resolution"] = "DISCOVERED_USER_SUMMARY"
                generated = _aware(payload.get("generated_at"))
                candidates.append((generated, league_id, enriched))

    if not candidates:
        return {}

    floor = _aware("1970-01-01T00:00:00+00:00")
    candidates.sort(
        key=lambda item: (item[0] or floor, -item[1]),
        reverse=True,
    )
    return candidates[0][2]


def _actual_price_changes(bootstrap: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for player in bootstrap.get("elements") or []:
        if not isinstance(player, Mapping):
            continue
        delta = player.get("cost_change_event")
        try:
            value = int(delta or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            rows.append(
                {
                    "element_id": int(player["id"]),
                    "player": player.get("web_name") or str(player["id"]),
                    "official_delta": round(value / 10.0, 1),
                    "current_price": round(float(player.get("now_cost") or 0) / 10.0, 1),
                    "classification": "FACT",
                }
            )
    return rows


def _route_economics(
    routes: Sequence[Mapping[str, Any]],
    *,
    team_resolution: Mapping[str, Any],
    predictor_artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    finance = dict(team_resolution.get("finance") or {})
    bank = finance.get("bank")
    price_by_id = _price_map(predictor_artifact)
    owned_by_id = {
        int(row["element_id"]): row
        for row in team_resolution.get("rows") or []
        if row.get("element_id") is not None
    }
    output = []
    for raw in routes:
        route = dict(raw)
        out_id = route.get("out_element_id")
        in_id = route.get("in_element_id")
        if out_id is None or in_id is None:
            continue
        out_row = owned_by_id.get(int(out_id)) or {}
        in_row = price_by_id.get(int(in_id)) or {}
        sell = out_row.get("sell_value")
        target_cost = in_row.get("now_cost")
        known = all(value is not None for value in (sell, target_cost, bank))
        budget = (float(sell) + float(bank)) if known else None
        target = float(target_cost) if known else None
        affordable = bool(known and budget >= target)
        plus = bool(known and budget >= target + 1)
        minus = bool(known and budget - 1 >= target)
        combined = bool(known and budget - 1 >= target + 1)
        output.append(
            {
                "route": route.get("route")
                or (
                    f"{out_row.get('name') or out_row.get('player') or 'OUT'} -> "
                    f"{in_row.get('player') or in_row.get('web_name') or route.get('in_name') or 'IN'}"
                ),
                "out_element_id": int(out_id),
                "in_element_id": int(in_id),
                "out_selling_price": sell,
                "in_current_price": target_cost,
                "bank_before": bank,
                "nominal_affordability": affordable if known else "UNKNOWN",
                "bank_after": (
                    round((budget - target) / 10.0, 1) if known else "UNKNOWN"
                ),
                "free_transfers": finance.get("free_transfers", "UNKNOWN"),
                "hit_cost": finance.get("hit_cost", "UNKNOWN"),
                "ft_hit_economics": (
                    "KNOWN"
                    if finance.get("free_transfers") is not None
                    and finance.get("hit_cost") is not None
                    else "UNKNOWN"
                ),
                "target_plus_0_1": plus if known else "UNKNOWN",
                "outgoing_minus_0_1": minus if known else "UNKNOWN",
                "combined_deterioration": combined if known else "UNKNOWN",
                "route_remains_affordable": combined if known else "UNKNOWN",
                "buyback_reversal_exit_risk": route.get(
                    "buyback_reversal_exit_risk", "UNAVAILABLE"
                ),
                "utility_1gw": route.get("utility_1gw", "UNAVAILABLE"),
                "utility_3gw": route.get("utility_3gw", "UNAVAILABLE"),
                "utility_5gw": route.get("utility_5gw", "UNAVAILABLE"),
                "football_action": str(route.get("football_action") or "WAIT").upper(),
                "classification": "INFERENCE",
            }
        )
    return output


def _decision_action(
    route_rows: Sequence[Mapping[str, Any]],
    *,
    team_supportable: bool,
) -> str:
    if not team_supportable:
        return "WAIT"
    for row in route_rows:
        if (
            str(row.get("football_action") or "").upper() == "ACT"
            and row.get("nominal_affordability") is True
        ):
            return "ACT"
    if any(
        str(row.get("football_action") or "").upper() in {"PREPARE", "ACT"}
        for row in route_rows
    ):
        return "PREPARE"
    return "WAIT"


def build_price_delivery_report(
    *,
    canonical_text: str,
    report_slot: str,
    planning_gw: int,
    bootstrap: Mapping[str, Any],
    team_resolution: Mapping[str, Any],
    predictor_artifact: Mapping[str, Any] | None,
    evaluated_universe: Sequence[Mapping[str, Any]] = (),
    universe_authority: str = "PARTIAL",
    transfer_routes: Sequence[Mapping[str, Any]] = (),
    mini_league: Mapping[str, Any] | None = None,
    source_lineage: Mapping[str, Any] | None = None,
    previous_price_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = canonical_mode_contract(canonical_text, "PRICE")
    expected_ids = list(contract.get("expected_section_ids") or [])
    expected_labels = list(contract.get("expected_visible_order") or [])
    if expected_ids != list(PRICE_SECTION_IDS) or len(expected_labels) != 12:
        raise PriceDeliveryError(
            "Canonical PRICE catalog does not define the exact 12-section delivery barrier"
        )

    predictor = dict(predictor_artifact or {})
    owned_rows = list(team_resolution.get("rows") or [])
    owned_ids = [
        int(value)
        for value in team_resolution.get("element_ids") or []
    ]
    rise = _strict_directional_price20(
        predictor_artifact=predictor,
        direction="RISE",
        owned_element_ids=owned_ids if team_resolution.get("supportable") else (),
    )
    fall = _strict_directional_price20(
        predictor_artifact=predictor,
        direction="FALL",
        owned_element_ids=owned_ids if team_resolution.get("supportable") else (),
    )
    our15 = build_actionable_price_radar(
        owned15=owned_rows,
        predictor_artifact=predictor,
    ) if owned_rows else {
        "state": "UNAVAILABLE",
        "rows": [],
        "available_count": 0,
        "expected_count": 15,
        "degradation_reason": team_resolution.get("reason")
        or "CURRENT15 unresolved",
    }
    watchlist = build_watchlist20(
        evaluated_universe=evaluated_universe,
        owned_element_ids=owned_ids if team_resolution.get("supportable") else (),
        universe_authority=universe_authority,
    )
    official_players = _player_map(bootstrap)
    team_names = {
        int(row["id"]): row.get("short_name") or row.get("name") or str(row["id"])
        for row in bootstrap.get("teams") or []
        if isinstance(row, Mapping) and row.get("id") is not None
    }
    owned_meta_by_id = {
        int(row["element_id"]): row
        for row in owned_rows
        if row.get("element_id") is not None
    }
    watch_price = build_actionable_price_radar(
        owned15=list(watchlist.get("rows") or []),
        predictor_artifact=predictor,
    ) if watchlist.get("rows") else {"rows": []}
    watch_by_id = {
        int(row["element_id"]): row
        for row in watch_price.get("rows") or []
        if row.get("element_id") is not None
    }
    for row in watchlist.get("rows") or []:
        price = watch_by_id.get(int(row.get("element_id") or 0)) or {}
        row.update(
            {
                "current_price": price.get("current_price"),
                "predictor_direction": price.get("direction"),
                "predictor_progress": price.get("official_or_provider_progress"),
                "eta_status": _eta_status(price),
                "football_relevance": row.get("canonical_score")
                or row.get("score")
                or row.get("rank"),
                "squad_relevance": "CURRENT_V12_WATCHLIST",
                "affordability_relevance": (
                    "EVALUATE_WITH_ROUTE_FINANCE"
                    if team_resolution.get("supportable")
                    else "OWNERSHIP_SCOPE_UNRESOLVED"
                ),
            }
        )

    for block in (rise, fall):
        for row in block.get("rows") or []:
            row["eta_status"] = _eta_status(row)
            official = official_players.get(int(row.get("element_id") or row.get("id") or -1)) or {}
            row["position"] = _position(
                row.get("position") or row.get("element_type") or official.get("element_type")
            )
            team_id = row.get("team_id") or row.get("team") or official.get("team")
            try:
                team_id_int = int(team_id) if team_id is not None else None
            except (TypeError, ValueError):
                team_id_int = None
            row["club"] = team_names.get(team_id_int, row.get("club") or "UNAVAILABLE")
            row["our15_flag"] = (
                "YES"
                if team_resolution.get("supportable")
                and int(row.get("element_id") or -1) in set(owned_ids)
                else "STALE_SCOPE"
                if not team_resolution.get("supportable")
                and int(row.get("element_id") or -1) in set(owned_ids)
                else "NO"
            )
            row["watchlist_flag"] = (
                "YES"
                if any(
                    int(w.get("element_id") or -2) == int(row.get("element_id") or -1)
                    for w in watchlist.get("rows") or []
                )
                else "NO"
            )

    for row in our15.get("rows") or []:
        row["eta_status"] = _eta_status(row)
        meta = owned_meta_by_id.get(int(row.get("element_id") or -1)) or {}
        row["position"] = _position(meta.get("position") or meta.get("element_type"))
        row["ownership_scope"] = team_resolution.get("state")
        row["direction"] = row.get("predictor_direction", "UNAVAILABLE")
        row["official_or_provider_progress"] = row.get(
            "predictor_progress", "UNAVAILABLE"
        )
        row["impact_on_our_decision"] = row.get(
            "decision_implication",
            row.get("sell_value_affordability_impact", "UNAVAILABLE"),
        )

    route_rows = _route_economics(
        transfer_routes,
        team_resolution=team_resolution,
        predictor_artifact=predictor,
    )
    action = _decision_action(
        route_rows,
        team_supportable=bool(team_resolution.get("supportable")),
    )
    official_changes = _actual_price_changes(bootstrap)
    previous = dict(previous_price_evidence or {})
    mini = dict(mini_league or {})
    mini_state = (
        "COMPLETE"
        if mini.get("complete") is True
        else "DEGRADED"
        if mini
        else "UNAVAILABLE"
    )
    predictor_health = str(
        predictor.get("health")
        or predictor.get("status")
        or predictor.get("source_health")
        or "UNAVAILABLE"
    ).upper()
    source = dict(source_lineage or {})

    price_risk = [
        row
        for row in (our15.get("rows") or [])
        if str(row.get("direction") or "").upper() in {"FALL", "RISE"}
    ]
    meaningful_route_risk = any(
        row.get("target_plus_0_1") is False
        or row.get("outgoing_minus_0_1") is False
        for row in route_rows
    )
    action_board = {
        "NOW": action,
        "NEXT": "Re-evaluate only with fresher football, ownership, finance or predictor evidence.",
        "TRIGGER TO ACT": (
            "Upstream football action ACT plus a legal supportable route whose economics justify timing."
        ),
        "LATEST SAFE DECISION POINT": source.get(
            "next_checkpoint", "NEXT PRICE CYCLE / next mandatory decision checkpoint"
        ),
        "COST OF WAITING": (
            "Material affordability risk exists on at least one supportable route."
            if meaningful_route_risk
            else "No supportable material route-cost loss is currently proven."
        ),
        "ABORT / REVERSAL": (
            "Abort early action if football edge, availability, role, legality or route economics deteriorate."
        ),
    }

    sections = [
        {
            "section_id": section_id,
            "label": label,
            "state": "COMPLETE",
            "content": {},
        }
        for section_id, label in zip(expected_ids, expected_labels)
    ]
    by_id = {row["section_id"]: row for row in sections}
    by_id["PRICE1"]["content"] = {
        "action": action,
        "material_change": (
            f"{len(official_changes)} confirmed Official price changes in current event snapshot"
            if official_changes
            else "No confirmed event price delta in current Official snapshot"
        ),
        "affordability_changed": (
            "MATERIAL_RISK" if meaningful_route_risk else "NO_PROVEN_MATERIAL_CHANGE"
        ),
        "price_pressure": len(price_risk),
        "football_decision_override": False,
    }
    by_id["PRICE2"].update(
        {
            "state": (
                "COMPLETE" if team_resolution.get("supportable") else
                "PARTIAL" if owned_rows else "UNAVAILABLE"
            ),
            "content": {
                "rows": list(our15.get("rows") or []),
                "ownership_state": team_resolution.get("state"),
                "source_class": team_resolution.get("source_class"),
                "gw": team_resolution.get("gw"),
                "observed_at": team_resolution.get("observed_at"),
            },
            "available_count": len(our15.get("rows") or []),
            "expected_count": 15,
            "degradation_reason": (
                None if team_resolution.get("supportable") else team_resolution.get("reason")
            ),
        }
    )
    by_id["PRICE3"]["content"] = {
        "official_changes": official_changes,
        "predictor_delta_state": (
            "AVAILABLE"
            if previous
            else "UNAVAILABLE: no previous valid PRICE evidence bound to this occurrence"
        ),
        "classification": {"official_changes": "FACT", "predictor": "MODEL"},
    }
    by_id["PRICE4"]["content"] = {
        "alerts": [
            {
                "player": row.get("name") or row.get("player"),
                "price_pressure": row.get("direction") or "UNAVAILABLE",
                "squad_need": f"{row.get('position') or 'Squad'} value / affordability watch",
                "football_horizon": "1GW / 3GW / 5GW",
                "affordability_impact": row.get("impact_on_our_decision") or "UNAVAILABLE",
                "action": action,
            }
            for row in price_risk[:10]
        ],
        "route_rows": route_rows,
    }
    by_id["PRICE5"].update(
        {
            "state": watchlist.get("state", "UNAVAILABLE"),
            "content": {"rows": list(watchlist.get("rows") or [])},
            "available_count": len(watchlist.get("rows") or []),
            "expected_count": 20,
            "degradation_reason": watchlist.get("degradation_reason"),
        }
    )
    for section_id, block in (("PRICE6", rise), ("PRICE7", fall)):
        by_id[section_id].update(
            {
                "state": block.get("state", "UNAVAILABLE"),
                "content": {"rows": list(block.get("rows") or [])},
                "available_count": len(block.get("rows") or []),
                "expected_count": 20,
                "degradation_reason": block.get("degradation_reason"),
            }
        )
    by_id["PRICE8"].update(
        {
            "state": "COMPLETE" if route_rows else "UNAVAILABLE",
            "content": {
                "routes": route_rows,
                "affordability_known_independently_of_ft_hit": True,
            },
            "degradation_reason": (
                None if route_rows
                else "no serious current transfer route with resolvable OUT/IN identity was supplied"
            ),
        }
    )
    mini_user = dict(mini.get("user_summary") or {})
    by_id["PRICE9"].update(
        {
            "state": mini_state,
            "content": {
                "league_name": mini.get("league_name"),
                "expected_manager_count": mini.get("expected_manager_count"),
                "collected_manager_count": mini.get("collected_manager_count"),
                "current_rank": mini_user.get("rank"),
                "current_points": mini_user.get("total"),
                "evidence_freshness": mini.get("generated_at", "UNAVAILABLE"),
                "price_route_impact": (
                    "UNAVAILABLE"
                    if not route_rows
                    else "Evaluate exposure only for supportable routes; price timing never overrides football quality."
                ),
                "mini_league_consequence": (
                    "Current standings/exposure scope is incomplete; do not manufacture player-level exposure."
                    if mini_state != "COMPLETE"
                    else "Use current league evidence only where exact player/route exposure is supportable."
                ),
                "exposure_rows": [],
            },
            "degradation_reason": (
                None if mini_state == "COMPLETE"
                else "current complete mini-league evidence unavailable"
            ),
        }
    )
    by_id["PRICE10"]["content"] = action_board
    by_id["PRICE11"]["content"] = {
        "official_timestamp": source.get("official_timestamp", "UNAVAILABLE"),
        "predictor_timestamp": predictor.get("checked_at") or predictor.get("generated_at") or "UNAVAILABLE",
        "personal_timestamp": team_resolution.get("observed_at"),
        "personal_status": team_resolution.get("state"),
        "mini_league_timestamp": mini.get("generated_at", "UNAVAILABLE"),
        "mini_league_status": mini_state,
        "core_logical_slot": source.get("core_logical_slot", "UNAVAILABLE"),
        "core_binding_state": source.get("core_binding_state", "UNAVAILABLE"),
        "core_run_id": source.get("core_run_id", "UNAVAILABLE"),
        "runtime_snapshot": source.get("runtime_snapshot", "UNAVAILABLE"),
        "predictor_health": predictor_health,
    }
    by_id["PRICE12"]["content"] = {
        "action": action,
        "key_price_risk": (
            "Supportable route affordability deterioration"
            if meaningful_route_risk
            else "No supportable route affordability deterioration proven"
        ),
        "affordability_threatened": meaningful_route_risk,
        "football_edge_justifies_action": action == "ACT",
        "next_checkpoint": action_board["LATEST SAFE DECISION POINT"],
        "final_judgement": (
            "Act only if the upstream football decision is ACT and the selected route remains legal and affordable."
            if action == "ACT"
            else "Do not force a transfer for price movement alone; preserve the football decision and reassess at the next checkpoint."
        ),
    }

    for row in sections:
        if row["state"] != "COMPLETE" and not row.get("degradation_reason"):
            row["degradation_reason"] = "scope-specific evidence unavailable"

    return {
        "schema": "V12_PRICE_DELIVERY_BARRIER_V1",
        "report_mode": "PRICE",
        "report_slot": report_slot,
        "planning_gw": int(planning_gw),
        "action": action,
        "sections": sections,
        "current15": dict(team_resolution),
        "watchlist20": watchlist,
        "rise20": rise,
        "fall20": fall,
        "source_lineage": source,
        "governance": {
            "structure_fail_operational": True,
            "data_degradation_allowed": True,
            "fabrication_allowed": False,
            "pre_rendered_exact20_required": False,
            "price_alone_can_force_act": False,
            "contemplated_transfer_mutates_current15": False,
        },
    }


def validate_price_report_model(report: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    sections = list(report.get("sections") or [])
    labels = [str(row.get("label") or "") for row in sections]
    ids = [str(row.get("section_id") or "") for row in sections]
    if ids != list(PRICE_SECTION_IDS):
        failures.append("PRICE_MODEL_SECTION_IDS_INVALID")
    if len(sections) != 12:
        failures.append(f"PRICE_MODEL_SECTION_COUNT={len(sections)}!=12")
    current = dict(report.get("current15") or {})
    if current.get("supportable"):
        rows = list(current.get("rows") or [])
        ids15 = [row.get("element_id") for row in rows]
        if len(rows) != 15 or len(set(ids15)) != 15:
            failures.append("PRICE_MODEL_CURRENT15_INVALID")
    for key in ("watchlist20", "rise20", "fall20"):
        block = dict(report.get(key) or {})
        rows = list(block.get("rows") or [])
        if str(block.get("state") or "").upper() == "COMPLETE":
            if len(rows) != 20:
                failures.append(f"{key.upper()}_FALSE_EXACT20")
            if key == "watchlist20":
                counts = Counter(_position(row.get("position")) for row in rows)
                if counts != Counter({"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}):
                    failures.append("WATCHLIST20_POSITION_SPLIT_INVALID")
    board = dict((sections[9].get("content") if len(sections) >= 10 else {}) or {})
    for field in ACTION_BOARD_FIELDS:
        if not str(board.get(field) or "").strip():
            failures.append(f"ACTION_BOARD_FIELD_MISSING={field}")
    if str(report.get("action") or "").upper() not in ACTIONS:
        failures.append("PRICE_ACTION_INVALID")
    return list(dict.fromkeys(failures))


def _cell(value: Any) -> str:
    if value is None:
        return "UNAVAILABLE"
    if isinstance(value, (dict, list, tuple)):
        return str(value).replace("|", "/")
    return str(value).replace("|", "/")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return [head, sep, *body]


def _human_scalar(value: Any) -> str:
    if value is None or value == "":
        return "UNAVAILABLE"
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return "UNAVAILABLE"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value)
    mapping = {
        "MATERIAL_RISK": "Material risk",
        "NO_PROVEN_MATERIAL_CHANGE": "No proven material change",
        "CURRENT_V12_WATCHLIST": "Current V12 watchlist",
        "EVALUATE_WITH_ROUTE_FINANCE": "Evaluate with route finance",
        "OWNERSHIP_SCOPE_UNRESOLVED": "Ownership scope unresolved",
        "STALE_SCOPE": "Stale scope",
        "KNOWN": "Known",
        "UNKNOWN": "Unknown",
        "AVAILABLE": "Available",
        "CURRENT": "Current",
        "COMPLETE": "Complete",
        "DEGRADED": "Degraded",
        "UNAVAILABLE": "Unavailable",
    }
    if text in mapping:
        return mapping[text]
    if re.fullmatch(r"[A-Z][A-Z0-9_ /-]{3,}", text) and "_" in text:
        return text.replace("_", " ").capitalize()
    return text


def _coverage(collected: Any, expected: Any) -> str:
    if collected is None or expected is None:
        return "UNAVAILABLE"
    return f"{collected}/{expected}"


def render_price_report(report: Mapping[str, Any]) -> str:
    contract_failures = validate_price_presentation_lock(load_price_presentation_lock())
    if contract_failures:
        raise PriceDeliveryError("PRICE presentation lock invalid: " + ",".join(contract_failures))

    sections = list(report.get("sections") or [])
    lines = [
        f"FPL MASTER V12 | PRICE | GW{report.get('planning_gw')}",
        "FACT: confirmed Official FPL evidence. MODEL: predictor/model evidence. INFERENCE: decision-layer interpretation.",
        "",
    ]
    current = dict(report.get("current15") or {})
    watch = dict(report.get("watchlist20") or {})

    for index, section in enumerate(sections, 1):
        lines.append(f"## PRICE {index} - {section.get('label')}")
        if str(section.get("state") or "").upper() != "COMPLETE":
            lines.append("Scope status: " + _human_scalar(section.get("state")))
            if section.get("degradation_reason"):
                lines.append("Scope note: " + _human_scalar(section.get("degradation_reason")))
        content = dict(section.get("content") or {})

        if index == 1:
            action = _human_scalar(content.get("action"))
            affordability = _human_scalar(content.get("affordability_changed"))
            pressure = content.get("price_pressure")
            lines.extend([
                "Current action",
                action,
                "",
                "Material change",
                _human_scalar(content.get("material_change")),
                "",
                "Affordability",
                affordability,
                "",
                "Price pressure",
                f"{pressure} owned-player pressure signal(s)" if pressure is not None else "UNAVAILABLE",
                "",
                "Football implication",
                "Price movement cannot override the upstream football decision.",
                "",
                "Conclusion",
                (
                    "Prepare/act only when football edge and executable route economics agree."
                    if str(content.get("action") or "").upper() in {"PREPARE","ACT"}
                    else "Wait unless new football or affordability evidence changes the route."
                ),
            ])
        elif index == 2:
            rows = list(content.get("rows") or [])
            sell_available = sum(
                row.get("authenticated_sell_value") not in {None, "", "UNAVAILABLE"}
                for row in rows
            )
            lines.extend([
                f"Current15 authority: {_human_scalar(content.get('source_class') or content.get('ownership_state'))}",
                f"Planning GW: {_human_scalar(content.get('gw'))}",
                f"Observed at: {_human_scalar(content.get('observed_at'))}",
                f"Squad completeness: {len(rows)}/15",
                f"Selling-value availability: {sell_available}/{len(rows) if rows else 15}",
            ])
            lines.extend(_table(
                ("Player","Pos","Market","Sell","Direction","Progress","ETA / Status","Decision impact"),
                [(
                    row.get("name") or row.get("player"),
                    row.get("position"),
                    row.get("current_price"),
                    row.get("authenticated_sell_value", "UNAVAILABLE"),
                    _human_scalar(row.get("direction")),
                    row.get("official_or_provider_progress"),
                    _human_scalar(row.get("eta_status")),
                    _human_scalar(row.get("impact_on_our_decision")),
                ) for row in rows],
            ))
            lines.append(
                "Lineage note: source="
                + _human_scalar(content.get("source_class"))
                + "; GW="
                + _human_scalar(content.get("gw"))
                + "; observed="
                + _human_scalar(content.get("observed_at"))
            )
        elif index == 3:
            changes = list(content.get("official_changes") or [])
            lines.append("FACT — confirmed Official change")
            if changes:
                lines.extend(_table(
                    ("Player","Official Δ","Current price","Evidence class"),
                    [(
                        row.get("player"), row.get("official_delta"), row.get("current_price"),
                        _human_scalar(row.get("classification")),
                    ) for row in changes],
                ))
            else:
                lines.append("No confirmed Official price delta in the bound snapshot.")
            lines.append("")
            lines.append("MODEL — predictor movement")
            lines.append(_human_scalar(content.get("predictor_delta_state")))
            lines.append("")
            lines.append("INFERENCE — decision consequence")
            lines.append("A predictor move is material only if it changes a supportable route or affordability window.")
        elif index == 4:
            alerts = list(content.get("alerts") or [])
            if alerts:
                lines.extend(_table(
                    ("Player","Price pressure","Squad need","Football horizon","Affordability impact","Action"),
                    [(
                        row.get("player"), _human_scalar(row.get("price_pressure")), row.get("squad_need"),
                        row.get("football_horizon"), _human_scalar(row.get("affordability_impact")),
                        _human_scalar(row.get("action")),
                    ) for row in alerts],
                ))
            else:
                lines.append("No evidence-backed owned-player price alert currently changes the decision.")
            routes = list(content.get("route_rows") or [])
            if routes:
                lines.append("")
                lines.extend(_table(
                    ("Route","Price risk","Current affordability","Football relevance","Decision impact"),
                    [(
                        row.get("route"),
                        "Material" if (row.get("target_plus_0_1") is False or row.get("outgoing_minus_0_1") is False) else "No material loss proven",
                        _human_scalar(row.get("nominal_affordability")),
                        f"1GW={row.get('utility_1gw')}; 3GW={row.get('utility_3gw')}; 5GW={row.get('utility_5gw')}",
                        _human_scalar(row.get("football_action")),
                    ) for row in routes],
                ))
        elif index == 5:
            rows = list(content.get("rows") or [])
            counts = Counter(_position(row.get("position")) for row in rows)
            admit_values = [row.get("admit") for row in rows if row.get("admit") is not None]
            actionable = sum(str(value).upper() in {"ACTIONABLE","ADMIT","YES","TRUE"} for value in admit_values) if admit_values else "UNAVAILABLE"
            lines.extend([
                f"Universe scanned: {_human_scalar(watch.get('universe_evaluated') or watch.get('eligible_universe_count') or watch.get('universe_count'))}",
                f"Scanner20: {len(rows)}/20",
                f"Composition: {counts.get('GK',0)} GK / {counts.get('DEF',0)} DEF / {counts.get('MID',0)} MID / {counts.get('FWD',0)} FWD",
                f"Actionable count: {actionable}",
            ])
            lines.extend(_table(
                ("Player","Pos","£","Direction","Progress","ETA / Status","Football relevance","Squad relevance","Affordability relevance"),
                [(
                    row.get("name") or row.get("player"), row.get("position"), row.get("current_price"),
                    _human_scalar(row.get("predictor_direction")), row.get("predictor_progress"),
                    _human_scalar(row.get("eta_status")), row.get("football_relevance"),
                    _human_scalar(row.get("squad_relevance")), _human_scalar(row.get("affordability_relevance")),
                ) for row in rows],
            ))
        elif index in {6, 7}:
            rows = list(content.get("rows") or [])
            lines.extend(_table(
                ("#","Player","Pos / Club","£","Progress","Direction","ETA / Status","Confidence","OUR15","Watchlist","As of"),
                [(
                    rank, row.get("player"),
                    f"{row.get('position') or 'UNAVAILABLE'} / {row.get('club') or 'UNAVAILABLE'}",
                    row.get("current_price"), row.get("projected_percent"), _human_scalar(row.get("direction")),
                    _human_scalar(row.get("eta_status")),
                    _human_scalar(row.get("confidence") or row.get("prediction_strength")),
                    _human_scalar(row.get("our15_flag")), _human_scalar(row.get("watchlist_flag")),
                    row.get("evidence_timestamp"),
                ) for rank, row in enumerate(rows, 1)],
            ))
            crossing = sum(
                bool(row.get("estimated_change_date_wib"))
                or str(row.get("date_state") or "").upper() == "EXPECTED_CHANGE_DATE"
                for row in rows
            )
            lines.append(f"Projected crossing / material timing: {crossing}/{len(rows) if rows else 20}")
        elif index == 8:
            routes = list(content.get("routes") or [])
            if routes:
                lines.append("Current economics")
                lines.extend(_table(
                    ("Route","OUT sell","IN price","Bank before","Affordable","Bank after","FT","Hit"),
                    [(
                        row.get("route"), row.get("out_selling_price"), row.get("in_current_price"),
                        row.get("bank_before"), _human_scalar(row.get("nominal_affordability")),
                        row.get("bank_after"), _human_scalar(row.get("free_transfers")),
                        _human_scalar(row.get("hit_cost")),
                    ) for row in routes],
                ))
                lines.append("")
                lines.append("Risk & football horizon")
                lines.extend(_table(
                    ("Route","Target +0.1","OUT -0.1","Combined","Route survives","1GW","3GW","5GW","Reversal risk"),
                    [(
                        row.get("route"), _human_scalar(row.get("target_plus_0_1")),
                        _human_scalar(row.get("outgoing_minus_0_1")), _human_scalar(row.get("combined_deterioration")),
                        _human_scalar(row.get("route_remains_affordable")), row.get("utility_1gw"),
                        row.get("utility_3gw"), row.get("utility_5gw"),
                        _human_scalar(row.get("buyback_reversal_exit_risk")),
                    ) for row in routes],
                ))
            else:
                lines.append("No supportable serious OUT -> IN route is available for economics materialization.")
            lines.append("Affordability and FT/HIT economics are separate authorities. Unknown FT/hit does not invalidate a supportable budget calculation.")
        elif index == 9:
            expected = content.get("expected_manager_count")
            collected = content.get("collected_manager_count")
            lines.extend([
                f"League: {_human_scalar(content.get('league_name'))}",
                f"Coverage: {_coverage(collected, expected)}",
                f"Current rank: {_human_scalar(content.get('current_rank'))}",
                f"Points: {_human_scalar(content.get('current_points'))}",
                f"Evidence freshness: {_human_scalar(content.get('evidence_freshness'))}",
            ])
            exposure = list(content.get("exposure_rows") or [])
            if exposure:
                lines.extend(_table(
                    ("Player / Route","Scope","Owned","Starter","Captain","EO","Price implication"),
                    [(
                        row.get("player_or_route"), row.get("scope"), row.get("owned"), row.get("starter"),
                        row.get("captain"), row.get("eo"), row.get("price_implication"),
                    ) for row in exposure],
                ))
            lines.extend([
                "",
                "Price route implication",
                _human_scalar(content.get("price_route_impact")),
                "",
                "Mini-league consequence",
                _human_scalar(content.get("mini_league_consequence")),
            ])
        elif index == 10:
            lines.extend(_table(
                ("Field","Current call"),
                [(field, _human_scalar(content.get(field))) for field in ACTION_BOARD_FIELDS],
            ))
        elif index == 11:
            rows = [
                ("Official FPL price", "Available" if content.get("official_timestamp") not in {None,"","UNAVAILABLE"} else "Unavailable", content.get("official_timestamp")),
                ("Official predictor", _human_scalar(content.get("predictor_health")), content.get("predictor_timestamp")),
                ("Current team / personal", _human_scalar(content.get("personal_status")), content.get("personal_timestamp")),
                ("Mini-league", _human_scalar(content.get("mini_league_status")), content.get("mini_league_timestamp")),
                ("Core/runtime evidence", _human_scalar(content.get("core_binding_state")), content.get("core_logical_slot")),
            ]
            lines.extend(_table(("Source","Status","As of"), rows))
            lines.append("Audit note: workflow/run/SHA lineage remains available in the canonical artifact, not the main report body.")
        elif index == 12:
            lines.extend([
                "Current action",
                _human_scalar(content.get("action")),
                "",
                "Key price risk",
                _human_scalar(content.get("key_price_risk")),
                "",
                "Affordability threatened?",
                _human_scalar(content.get("affordability_threatened")),
                "",
                "Does football edge justify action?",
                _human_scalar(content.get("football_edge_justifies_action")),
                "",
                "Next checkpoint",
                _human_scalar(content.get("next_checkpoint")),
                "",
                "One-sentence final judgement",
                _human_scalar(content.get("final_judgement")),
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def _parse_sections(body: str) -> tuple[list[str], dict[str, str]]:
    matches = list(re.finditer(
        r"(?m)^## PRICE (?P<number>\d+) - (?P<label>.+?)\s*$",
        body,
    ))
    order: list[str] = []
    content: dict[str, str] = {}
    for index, match in enumerate(matches):
        number = int(match.group("number"))
        section_id = f"PRICE{number}"
        order.append(section_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content[section_id] = body[match.end():end]
    return order, content


def _table_rows(section: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return headers, rows


def validate_price_visible_body(
    body: str,
    *,
    report: Mapping[str, Any],
) -> list[str]:
    failures = validate_price_report_model(report)
    failures.extend(validate_price_presentation_lock())
    order, sections = _parse_sections(str(body or ""))
    expected = [f"PRICE{i}" for i in range(1, 13)]
    if order != expected:
        failures.append("VISIBLE_PRICE_SECTION_SEQUENCE_MISMATCH")
    if len(order) != 12:
        failures.append(f"VISIBLE_PRICE_SECTION_COUNT={len(order)}!=12")
    if not body.strip():
        failures.append("VISIBLE_PRICE_BODY_EMPTY")
    if "FACT:" not in body or "MODEL:" not in body or "INFERENCE:" not in body:
        failures.append("VISIBLE_FACT_MODEL_INFERENCE_LABELS_MISSING")

    exact_headers = {
        "PRICE2": ["Player","Pos","Market","Sell","Direction","Progress","ETA / Status","Decision impact"],
        "PRICE3": ["Player","Official Δ","Current price","Evidence class"],
        "PRICE5": ["Player","Pos","£","Direction","Progress","ETA / Status","Football relevance","Squad relevance","Affordability relevance"],
        "PRICE6": ["#","Player","Pos / Club","£","Progress","Direction","ETA / Status","Confidence","OUR15","Watchlist","As of"],
        "PRICE7": ["#","Player","Pos / Club","£","Progress","Direction","ETA / Status","Confidence","OUR15","Watchlist","As of"],
        "PRICE10": ["Field","Current call"],
        "PRICE11": ["Source","Status","As of"],
    }
    for sid, expected_header in exact_headers.items():
        headers, _ = _table_rows(sections.get(sid, ""))
        if headers and headers != expected_header:
            failures.append(f"VISIBLE_{sid}_COLUMNS_MISMATCH")

    current = dict(report.get("current15") or {})
    headers, rows = _table_rows(sections.get("PRICE2", ""))
    if current.get("supportable"):
        if len(rows) != 15:
            failures.append(f"VISIBLE_OUR15_COUNT={len(rows)}!=15")
        names = [row.get("Player") for row in rows]
        if len(set(names)) != len(names):
            failures.append("VISIBLE_OUR15_DUPLICATE")
        if "ETA / Status" not in headers or any(not row.get("ETA / Status") for row in rows):
            failures.append("VISIBLE_OUR15_ETA_MISSING")

    for key, section_id, position_split in (
        ("watchlist20", "PRICE5", True),
        ("rise20", "PRICE6", False),
        ("fall20", "PRICE7", False),
    ):
        block = dict(report.get(key) or {})
        headers, visible_rows = _table_rows(sections.get(section_id, ""))
        if visible_rows and (
            "ETA / Status" not in headers
            or any(not row.get("ETA / Status") for row in visible_rows)
        ):
            failures.append(f"VISIBLE_{key.upper()}_ETA_MISSING")
        if str(block.get("state") or "").upper() == "COMPLETE":
            if len(visible_rows) != 20:
                failures.append(f"VISIBLE_{key.upper()}_COUNT={len(visible_rows)}!=20")
            if position_split:
                counts = Counter(_position(row.get("Pos")) for row in visible_rows)
                if counts != Counter({"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}):
                    failures.append("VISIBLE_WATCHLIST20_POSITION_SPLIT_INVALID")

    action_headers, action_rows = _table_rows(sections.get("PRICE10", ""))
    if action_headers != ["Field","Current call"]:
        failures.append("VISIBLE_ACTION_BOARD_COLUMNS_MISMATCH")
    action_map = {row.get("Field"): row.get("Current call") for row in action_rows}
    if len(action_rows) != 6:
        failures.append(f"VISIBLE_ACTION_BOARD_COUNT={len(action_rows)}!=6")
    for field in ACTION_BOARD_FIELDS:
        if not str(action_map.get(field) or "").strip():
            failures.append(f"VISIBLE_ACTION_BOARD_FIELD_MISSING={field}")

    first = sections.get("PRICE1", "")
    if not re.search(r"(?m)^Current action\s*\n(?:WAIT|PREPARE|ACT)\s*$", first):
        failures.append("VISIBLE_PRICE_ACTION_MISSING")

    final = sections.get("PRICE12", "")
    if "One-sentence final judgement" not in final:
        failures.append("VISIBLE_FINAL_PRICE_JUDGEMENT_MISSING")

    forbidden = {
        "element_id": r"\belement_id\b",
        "entry_id": r"\bentry_id\b",
        "user_summary": r"\buser_summary\s*[:=]",
        "raw_dict": r"\{[^\n]{0,200}['\"][^\n]{0,200}\}",
        "actual_paths": r"\bactual_paths\s*=",
        "raw_run_id": r"\b(?:run_id|workflow_id)\b",
        "raw_sha": r"\b(?:sha256|fingerprint)\b",
        "generic_key_value": r"(?m)^[A-Za-z_][A-Za-z0-9_]{2,}\s*=\s*\S+",
    }
    for label, pattern in forbidden.items():
        if re.search(pattern, body, flags=re.IGNORECASE):
            failures.append(f"VISIBLE_MACHINE_LANGUAGE_LEAK={label}")

    if "MINI_LEAGUE_STATE:" in body:
        failures.append("VISIBLE_PRICE9_GENERIC_DUMP")
    if "Ownership scope" in body:
        failures.append("VISIBLE_INTERNAL_OWNERSHIP_SCOPE")
    return list(dict.fromkeys(failures))

def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _planning_gw_from_bootstrap(bootstrap: Mapping[str, Any]) -> int:
    events = [
        dict(row)
        for row in bootstrap.get("events") or []
        if isinstance(row, Mapping)
    ]
    next_rows = [row for row in events if row.get("is_next") is True]
    if next_rows:
        return int(next_rows[0]["id"])
    current = [row for row in events if row.get("is_current") is True]
    if current:
        return int(current[0]["id"]) + 1
    unfinished = [
        int(row.get("id") or 0)
        for row in events
        if not row.get("finished")
    ]
    unfinished = [gw for gw in unfinished if gw > 0]
    return min(unfinished) if unfinished else 1


def _expected_core_slot(report_slot: str) -> str | None:
    parsed = _aware(report_slot)
    if parsed is None:
        return None
    return parsed.replace(minute=0, second=0, microsecond=0).isoformat()


def _core_lineage(
    *,
    report_slot: str,
    publish_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _expected_core_slot(report_slot)
    actual_dt = _aware(publish_integrity.get("logical_slot"))
    requested = _aware(report_slot)
    actual = (
        actual_dt.astimezone(requested.tzinfo).isoformat()
        if actual_dt is not None and requested is not None
        else None
    )
    return {
        "expected_core_slot": expected,
        "actual_core_slot": actual,
        "core_binding_state": "PASS" if expected and actual == expected else "DEGRADED",
        "core_logical_slot": actual or "UNAVAILABLE",
        "core_run_id": publish_integrity.get("run_id") or "UNAVAILABLE",
        "official_timestamp": publish_integrity.get("observed_at")
        or publish_integrity.get("generated_at")
        or "UNAVAILABLE",
        "runtime_snapshot": publish_integrity.get("candidate_generation_id")
        or publish_integrity.get("tree_sha256")
        or "UNAVAILABLE",
    }


def _scenario_routes(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expose only structurally explicit OUT/IN contemplated routes.

    A recommendation/scenario without both element identities is deliberately not
    converted into a transfer route, and execution is never inferred.
    """
    output = []
    for raw in state.get("active_scenarios") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("execution_state") or "").upper() == "EXECUTED":
            continue
        out_id = raw.get("out_element_id")
        in_id = raw.get("in_element_id")
        if out_id is None or in_id is None:
            continue
        output.append(
            {
                "route": raw.get("scenario_id") or raw.get("route"),
                "out_element_id": out_id,
                "in_element_id": in_id,
                "football_action": raw.get("operational_action")
                or raw.get("action")
                or "WAIT",
                "utility_1gw": raw.get("utility_1gw", "UNAVAILABLE"),
                "utility_3gw": raw.get("utility_3gw", "UNAVAILABLE"),
                "utility_5gw": raw.get("utility_5gw", "UNAVAILABLE"),
                "buyback_reversal_exit_risk": raw.get(
                    "reversal_conditions", "UNAVAILABLE"
                ),
            }
        )
    return output


def run_price_occurrence(
    *,
    runtime_data_root: Path,
    canonical_path: Path,
    state_path: Path,
    report_slot: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Materialize and visible-body validate one PRICE occurrence.

    This path is intentionally independent of Stage-3/MC. PRICE consumes the
    existing factual/model owners needed for PRICE and never relaxes DEEP.
    """
    canonical_text = canonical_path.read_text(encoding="utf-8")
    state = _read_json(state_path, {}) or {}
    official_payload = _read_json(
        runtime_data_root / "data/v6/current/official_fpl.json", {}
    ) or {}
    official = official_payload.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    fixtures = official.get("fixtures") or []
    if not isinstance(bootstrap, Mapping) or not bootstrap.get("elements"):
        raise PriceDeliveryError("Official FPL bootstrap unavailable")
    if not isinstance(fixtures, list):
        fixtures = []
    planning_gw = _planning_gw_from_bootstrap(bootstrap)

    current_team = _read_json(
        runtime_data_root / "data/v6/personal/current_team.json", {}
    ) or {}
    submitted = _read_json(
        runtime_data_root / "data/v6/personal/submitted_picks.json", {}
    ) or {}
    explicit = explicit_user_evidence_from_state(state)
    resolution = resolve_current15(
        planning_gw=planning_gw,
        bootstrap=bootstrap,
        explicit_user_evidence=explicit,
        authenticated_current_team=current_team,
        personal_artifact=None,
        last_good_evidence=submitted,
    )

    evaluated_universe: list[dict[str, Any]] = []
    universe_authority = "PARTIAL"
    analytics_error = None
    try:
        from src.models.team_strength import build_team_strength
        from src.models.v12_analytics_foundation import (
            load_v6_analytics_foundation,
            require_match_foundation,
        )
        from src.models.historical_projection import build as build_player_projections
        from src.models.official_role_evidence import attach_official_role_evidence
        from src.engines.v12_tactical_role import attach_tactical_role_scores
        from src.models.v12_stage1_analytics import build_canonical_universe

        strength = build_team_strength(bootstrap, fixtures)
        foundation = require_match_foundation(
            load_v6_analytics_foundation(
                runtime_data_root,
                bootstrap=bootstrap,
                planning_gw=planning_gw,
                strength=strength,
            )
        )
        projections = build_player_projections(
            bootstrap,
            strength,
            planning_gw,
            foundation.get("historical_prior") or {},
            player_features_payload=foundation.get("player_features_payload") or {},
            player_match_rows=foundation.get("player_match_rows") or [],
            opponent_history_rows=foundation.get("opponent_history_rows") or [],
            opponent_history_scope=foundation.get("opponent_history_scope"),
        )
        attach_official_role_evidence(projections, bootstrap)
        attach_tactical_role_scores(
            projections,
            planning_gw,
            team_strength=strength,
        )
        canonical_universe = build_canonical_universe(projections)
        evaluated_universe = list(canonical_universe.get("players") or [])
        universe_authority = (
            "FULL"
            if canonical_universe.get("status") == "COMPLETE"
            else "PARTIAL"
        )
    except Exception as exc:
        analytics_error = f"{type(exc).__name__}: {exc}"

    predictor = _read_json(
        runtime_data_root / "data/v6/current/official_price_predictor.json", {}
    ) or {}
    standings = _load_priority_mini_league(runtime_data_root)
    publish_integrity = _read_json(
        runtime_data_root / "data/v6/health/publish_integrity.json", {}
    ) or {}
    lineage = _core_lineage(
        report_slot=report_slot,
        publish_integrity=publish_integrity,
    )
    lineage["analytics_state"] = (
        "FULL" if universe_authority == "FULL" else "DEGRADED"
    )
    lineage["analytics_reason"] = analytics_error
    lineage["next_checkpoint"] = "NEXT PRICE CYCLE / next mandatory decision checkpoint"

    report = build_price_delivery_report(
        canonical_text=canonical_text,
        report_slot=report_slot,
        planning_gw=planning_gw,
        bootstrap=bootstrap,
        team_resolution=resolution,
        predictor_artifact=predictor,
        evaluated_universe=evaluated_universe,
        universe_authority=universe_authority,
        transfer_routes=_scenario_routes(state),
        mini_league=standings,
        source_lineage=lineage,
        previous_price_evidence=None,
    )
    model_failures = validate_price_report_model(report)
    body = render_price_report(report)
    visible_failures = validate_price_visible_body(body, report=report)

    pre_render_status = "PASS" if not model_failures else "FAIL"
    post_render_status = "PASS" if not visible_failures else "FAIL"
    human_facing_status = post_render_status
    runner_status = (
        "PASS"
        if pre_render_status == "PASS"
        and post_render_status == "PASS"
        and human_facing_status == "PASS"
        else "FAIL"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_sha = hashlib.sha256(
        canonical_text.encode("utf-8")
    ).hexdigest()
    execution_proof = {
        "schema": "V12_PRICE_EXECUTION_PROOF_V1",
        "runner_status": runner_status,
        "report_mode": "PRICE",
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "pre_render_qa_status": pre_render_status,
        "post_render_qa_status": post_render_status,
        "human_facing_qa_status": human_facing_status,
        "pre_render_failures": model_failures,
        "post_render_failures": visible_failures,
        "top_level_section_count": len(report.get("sections") or []),
        "current15_state": resolution.get("state"),
        "current15_supportable": resolution.get("supportable"),
        "watchlist20_state": (report.get("watchlist20") or {}).get("state"),
        "rise20_state": (report.get("rise20") or {}).get("state"),
        "fall20_state": (report.get("fall20") or {}).get("state"),
        "core_binding_state": lineage.get("core_binding_state"),
        "canonical_content_sha256": canonical_sha,
        "governance": {
            "v6_mutated": False,
            "scheduler_created_or_changed": False,
            "issue_431_transport_changed": False,
            "deep_contract_changed_by_runner": False,
            "stage3_or_mc_executed": False,
            "qa_relaxed": False,
            "legacy_short_fallback_allowed": False,
        },
    }
    bundle = {
        "schema": "FPL_MASTER_V12_PRICE_REPORT_BUNDLE_V1",
        "authority": str(canonical_path),
        "state_authority": False,
        "report_mode": "PRICE",
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "runner_status": runner_status,
        "report": report,
        "visible_body": body,
        "human_facing_validation": {
            "status": human_facing_status,
            "failures": visible_failures,
        },
        "execution_proof": execution_proof,
        "source_fingerprints": {
            "official_fpl": hashlib.sha256(
                json.dumps(
                    official_payload,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
            "predictor": hashlib.sha256(
                json.dumps(
                    predictor,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
            "current_team": hashlib.sha256(
                json.dumps(
                    current_team,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
            "mini_league": hashlib.sha256(
                json.dumps(
                    standings,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
        },
    }
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(execution_proof, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return bundle
