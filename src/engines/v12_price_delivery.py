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
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_price20,
    build_watchlist20,
)


PRICE_SECTION_LABELS = (
    "PRICE DECISION / CURRENT STATUS",
    "OUR15 PRICE & VALUE",
    "PRICE DELTA / MATERIAL CHANGES",
    "TEAM-NEEDS PRICE ALERT",
    "WATCHLIST20",
    "RISE20",
    "FALL20",
    "PACKAGE / AFFORDABILITY / TRANSFER ECONOMICS",
    "MINI-LEAGUE PRICE IMPACT",
    "ACTION BOARD",
    "SOURCE HEALTH / PRICE-CYCLE / LINEAGE",
    "FINAL PRICE JUDGEMENT",
)
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
                "sell_value": row.get("selling_price", row.get("sell_value")),
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
                or f"{int(out_id)} -> {int(in_id)}",
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
    expected_labels = list(contract.get("expected_visible_order") or [])
    if expected_labels != list(PRICE_SECTION_LABELS):
        raise PriceDeliveryError(
            "Canonical PRICE catalog does not match the 12-section delivery barrier"
        )

    predictor = dict(predictor_artifact or {})
    owned_rows = list(team_resolution.get("rows") or [])
    owned_ids = [
        int(value)
        for value in team_resolution.get("element_ids") or []
    ]
    rise = build_price20(
        predictor_artifact=predictor,
        direction="RISE",
        owned_element_ids=owned_ids if team_resolution.get("supportable") else (),
    )
    fall = build_price20(
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
        row["ownership_scope"] = team_resolution.get("state")

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
            "section_id": f"PRICE{index}",
            "label": label,
            "state": "COMPLETE",
            "content": {},
        }
        for index, label in enumerate(PRICE_SECTION_LABELS, 1)
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
                "element_id": row.get("element_id"),
                "player": row.get("name") or row.get("player"),
                "reason": "owned price pressure",
                "horizon": "1GW / 3GW / 5GW football decision remains upstream",
                "classification": "INFERENCE",
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
    by_id["PRICE9"].update(
        {
            "state": mini_state,
            "content": {
                "league_name": mini.get("league_name"),
                "expected_manager_count": mini.get("expected_manager_count"),
                "collected_manager_count": mini.get("collected_manager_count"),
                "user_summary": mini.get("user_summary"),
                "price_route_impact": (
                    "UNAVAILABLE"
                    if not route_rows
                    else "evaluate ownership/starter/captain exposure against each supportable route"
                ),
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
        "core_run_id": source.get("core_run_id", "UNAVAILABLE"),
        "runtime_snapshot": source.get("runtime_snapshot", "UNAVAILABLE"),
        "predictor_health": predictor_health,
    }
    by_id["PRICE12"]["content"] = {
        "action": action,
        "key_price_risk": (
            "supportable route affordability deterioration"
            if meaningful_route_risk
            else "no supportable route affordability deterioration proven"
        ),
        "affordability_threatened": meaningful_route_risk,
        "football_edge_justifies_action": action == "ACT",
        "next_checkpoint": action_board["LATEST SAFE DECISION POINT"],
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
    if labels != list(PRICE_SECTION_LABELS):
        failures.append("PRICE_MODEL_SECTION_ORDER_INVALID")
    if ids != [f"PRICE{i}" for i in range(1, 13)]:
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


def render_price_report(report: Mapping[str, Any]) -> str:
    sections = list(report.get("sections") or [])
    lines = [
        f"FPL MASTER V12 | PRICE | GW{report.get('planning_gw')}",
        "FACT: Official FPL factual evidence. MODEL: price/model evidence. INFERENCE: decision-layer synthesis.",
        "",
    ]
    for index, section in enumerate(sections, 1):
        lines.append(f"## PRICE {index} - {section.get('label')}")
        lines.append(f"STATUS: {section.get('state')}")
        if section.get("degradation_reason"):
            lines.append(f"DEGRADATION_REASON: {section.get('degradation_reason')}")
        content = dict(section.get("content") or {})

        if index == 1:
            lines.append(f"ACTION: {content.get('action')}")
            lines.append(f"Material change: {_cell(content.get('material_change'))}")
            lines.append(f"Affordability: {_cell(content.get('affordability_changed'))}")
            lines.append(f"Price pressure: {_cell(content.get('price_pressure'))}")
            lines.append("Football decision precedence: price alone does not force ACT.")
        elif index == 2:
            rows = list(content.get("rows") or [])
            lines.extend(_table(
                ("element_id", "Player", "Position", "Market", "Sell", "Direction", "Progress", "ETA/status", "Implication", "Ownership scope"),
                [(
                    row.get("element_id"),
                    row.get("name") or row.get("player"),
                    row.get("position"),
                    row.get("current_price"),
                    row.get("selling_price", row.get("sell_value")),
                    row.get("direction"),
                    row.get("official_or_provider_progress"),
                    row.get("eta_status"),
                    row.get("impact_on_our_decision"),
                    row.get("ownership_scope"),
                ) for row in rows],
            ))
            lines.append(
                "Evidence: source="
                + _cell(content.get("source_class"))
                + " gw="
                + _cell(content.get("gw"))
                + " timestamp="
                + _cell(content.get("observed_at"))
            )
        elif index == 3:
            changes = list(content.get("official_changes") or [])
            if changes:
                lines.extend(_table(
                    ("element_id", "Player", "Official delta", "Current price", "Class"),
                    [(
                        row.get("element_id"), row.get("player"), row.get("official_delta"),
                        row.get("current_price"), row.get("classification")
                    ) for row in changes],
                ))
            else:
                lines.append("FACT: No current event official price delta rows in the bound snapshot.")
            lines.append("MODEL: " + _cell(content.get("predictor_delta_state")))
        elif index == 4:
            alerts = list(content.get("alerts") or [])
            if alerts:
                lines.extend(_table(
                    ("element_id", "Player", "Reason", "Horizon", "Class"),
                    [(
                        row.get("element_id"), row.get("player"), row.get("reason"),
                        row.get("horizon"), row.get("classification")
                    ) for row in alerts],
                ))
            else:
                lines.append("INFERENCE: No evidence-backed team-needs price alert is currently proven.")
        elif index == 5:
            rows = list(content.get("rows") or [])
            lines.extend(_table(
                ("element_id", "Player", "Position", "Price", "Direction", "Progress", "ETA/status", "Football relevance", "Squad relevance", "Affordability relevance"),
                [(
                    row.get("element_id"), row.get("name") or row.get("player"), row.get("position"),
                    row.get("current_price"), row.get("predictor_direction"), row.get("predictor_progress"),
                    row.get("eta_status"), row.get("football_relevance"), row.get("squad_relevance"),
                    row.get("affordability_relevance")
                ) for row in rows],
            ))
        elif index in {6, 7}:
            rows = list(content.get("rows") or [])
            lines.extend(_table(
                ("Rank", "element_id", "Player", "Pos/team", "Price", "Progress", "Direction", "ETA/status", "Urgency/confidence", "OUR15", "WATCHLIST", "Timestamp"),
                [(
                    rank, row.get("element_id"), row.get("player"),
                    f"{POSITION_BY_TYPE.get(int(row.get('element_type') or 0), row.get('element_type'))}/{row.get('team')}",
                    row.get("current_price"), row.get("projected_percent"), row.get("direction"),
                    row.get("eta_status"), row.get("prediction_strength"), row.get("our15_flag"),
                    row.get("watchlist_flag"), row.get("evidence_timestamp")
                ) for rank, row in enumerate(rows, 1)],
            ))
        elif index == 8:
            routes = list(content.get("routes") or [])
            if routes:
                lines.extend(_table(
                    ("Route", "OUT sell", "IN price", "Bank before", "Affordable", "Bank after", "FT", "Hit", "FT/HIT economics", "Target +0.1", "OUT -0.1", "Combined", "Route survives", "1GW", "3GW", "5GW", "Reversal risk"),
                    [(
                        row.get("route"), row.get("out_selling_price"), row.get("in_current_price"),
                        row.get("bank_before"), row.get("nominal_affordability"), row.get("bank_after"),
                        row.get("free_transfers"), row.get("hit_cost"), row.get("ft_hit_economics"),
                        row.get("target_plus_0_1"), row.get("outgoing_minus_0_1"),
                        row.get("combined_deterioration"), row.get("route_remains_affordable"),
                        row.get("utility_1gw"), row.get("utility_3gw"), row.get("utility_5gw"),
                        row.get("buyback_reversal_exit_risk")
                    ) for row in routes],
                ))
            else:
                lines.append("INFERENCE: No supportable serious OUT -> IN route is available for economics materialization.")
            lines.append("Affordability and FT/HIT economics are separate contracts.")
        elif index == 9:
            lines.append("MINI_LEAGUE_STATE: " + str(section.get("state")))
            for key, value in content.items():
                lines.append(f"{key}: {_cell(value)}")
        elif index == 10:
            for field in ACTION_BOARD_FIELDS:
                lines.append(f"{field}: {_cell(content.get(field))}")
        elif index == 11:
            for key, value in content.items():
                lines.append(f"{key}: {_cell(value)}")
        elif index == 12:
            lines.append(f"ACTION: {_cell(content.get('action'))}")
            lines.append(f"Key price risk: {_cell(content.get('key_price_risk'))}")
            lines.append(f"Affordability threatened: {_cell(content.get('affordability_threatened'))}")
            lines.append(f"Football edge justifies action: {_cell(content.get('football_edge_justifies_action'))}")
            lines.append(f"Next checkpoint: {_cell(content.get('next_checkpoint'))}")
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

    current = dict(report.get("current15") or {})
    headers, rows = _table_rows(sections.get("PRICE2", ""))
    if current.get("supportable"):
        if len(rows) != 15:
            failures.append(f"VISIBLE_OUR15_COUNT={len(rows)}!=15")
        ids = [row.get("element_id") for row in rows]
        if len(set(ids)) != len(ids):
            failures.append("VISIBLE_OUR15_DUPLICATE")
        if "ETA/status" not in headers or any(not row.get("ETA/status") for row in rows):
            failures.append("VISIBLE_OUR15_ETA_MISSING")

    for key, section_id, position_split in (
        ("watchlist20", "PRICE5", True),
        ("rise20", "PRICE6", False),
        ("fall20", "PRICE7", False),
    ):
        block = dict(report.get(key) or {})
        headers, visible_rows = _table_rows(sections.get(section_id, ""))
        if visible_rows and (
            "ETA/status" not in headers
            or any(not row.get("ETA/status") for row in visible_rows)
        ):
            failures.append(f"VISIBLE_{key.upper()}_ETA_MISSING")
        if str(block.get("state") or "").upper() == "COMPLETE":
            if len(visible_rows) != 20:
                failures.append(f"VISIBLE_{key.upper()}_COUNT={len(visible_rows)}!=20")
            if position_split:
                counts = Counter(_position(row.get("Position")) for row in visible_rows)
                if counts != Counter({"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}):
                    failures.append("VISIBLE_WATCHLIST20_POSITION_SPLIT_INVALID")

    action_section = sections.get("PRICE10", "")
    for field in ACTION_BOARD_FIELDS:
        if not re.search(rf"(?m)^{re.escape(field)}:\s*\S", action_section):
            failures.append(f"VISIBLE_ACTION_BOARD_FIELD_MISSING={field}")

    first = sections.get("PRICE1", "")
    action_match = re.search(r"(?m)^ACTION:\s*(WAIT|PREPARE|ACT)\s*$", first)
    if not action_match:
        failures.append("VISIBLE_PRICE_ACTION_MISSING")
    elif action_match.group(1) != str(report.get("action") or "").upper():
        failures.append("VISIBLE_PRICE_ACTION_MISMATCH")

    final = sections.get("PRICE12", "")
    if not re.search(r"(?m)^ACTION:\s*(WAIT|PREPARE|ACT)\s*$", final):
        failures.append("VISIBLE_FINAL_PRICE_JUDGEMENT_ACTION_MISSING")

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
    standings = _read_json(
        runtime_data_root / "data/v6/mini_leagues/9477/standings.json", {}
    ) or {}
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
