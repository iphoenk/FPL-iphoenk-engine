from __future__ import annotations

"""Report-plane delivery guards for V12 DEEP.

This module never computes football projections, Monte Carlo paths, package
utility, mini-league exposure, or transfer economics. It only reconciles
already-produced personal evidence and validates that authoritative V12
analytics are materially visible in the DEEP report.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence


def _aware_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _identity_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("players")
    if not isinstance(raw, list):
        raw = payload.get("picks")
    return [dict(row) for row in (raw or []) if isinstance(row, Mapping)]


def select_personal_evidence(
    candidates: Sequence[Mapping[str, Any]],
    *,
    planning_gw: int,
) -> dict[str, Any]:
    """Select freshest semantically valid personal evidence.

    AUTH_EXPIRED timestamps cannot outrank a valid authenticated or explicitly
    user-confirmed current-team candidate. Previous-GW submitted picks are
    identity fallback only and are never allowed to invent current finance.
    """
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(candidates):
        payload = dict(raw.get("payload") or {})
        rows = _identity_rows(payload)
        observed = (
            raw.get("observed_at")
            or payload.get("generated_at")
            or payload.get("updated_at")
        )
        ts = _aware_timestamp(observed)
        source_class = str(raw.get("source_class") or "").upper()
        auth_state = str(
            raw.get("auth_state")
            or payload.get("auth_state")
            or (payload.get("availability") or {}).get("authenticated_state")
            or ""
        ).upper()
        gw_raw = raw.get("gw", payload.get("gw"))
        try:
            gw = int(gw_raw) if gw_raw is not None else None
        except (TypeError, ValueError):
            gw = None
        exact15 = len(rows) == 15 and len({
            int(row.get("element_id") or row.get("element") or 0)
            for row in rows
            if int(row.get("element_id") or row.get("element") or 0) > 0
        }) == 15
        user_current = bool(
            source_class == "USER_CONFIRMED"
            and raw.get("applicable_planning_gw") == planning_gw
            and raw.get("explicit_confirmation") is True
        )
        authenticated = auth_state == "AUTH_AVAILABLE"
        previous_gw = gw is not None and gw < planning_gw
        current_semantic = bool(
            exact15
            and (
                user_current
                or authenticated
            )
        )
        normalized.append({
            "index": index,
            "source": raw.get("source") or f"candidate:{index}",
            "source_class": source_class or "UNKNOWN",
            "payload": payload,
            "rows": rows,
            "observed_at": observed,
            "timestamp": ts,
            "gw": gw,
            "auth_state": auth_state or "UNKNOWN",
            "exact15": exact15,
            "authenticated": authenticated,
            "user_current": user_current,
            "previous_gw": previous_gw,
            "current_semantic": current_semantic,
        })

    valid = [row for row in normalized if row["current_semantic"]]
    if valid:
        selected = max(
            valid,
            key=lambda row: (
                row["timestamp"].timestamp()
                if row["timestamp"] is not None
                else float("-inf"),
                1 if row["authenticated"] else 0,
                -row["index"],
            ),
        )
        return {
            **selected,
            "resolution_status": "CURRENT_VALID",
            "stale": False,
            "finance_allowed": bool(
                selected["authenticated"] or selected["user_current"]
            ),
            "candidate_count": len(normalized),
        }

    identity_fallbacks = [row for row in normalized if row["exact15"]]
    if not identity_fallbacks:
        return {
            "resolution_status": "UNAVAILABLE",
            "stale": True,
            "finance_allowed": False,
            "candidate_count": len(normalized),
            "rows": [],
            "payload": {},
        }
    selected = max(
        identity_fallbacks,
        key=lambda row: (
            row["timestamp"].timestamp() if row["timestamp"] else float("-inf"),
            1 if row["source_class"] == "OFFICIAL_SUBMITTED_PICKS" else 0,
            -row["index"],
        ),
    )
    return {
        **selected,
        "resolution_status": (
            "PREVIOUS_GW_IDENTITY_FALLBACK"
            if selected["previous_gw"]
            else "STALE_IDENTITY_FALLBACK"
        ),
        "stale": True,
        "finance_allowed": False,
        "candidate_count": len(normalized),
    }


def validate_deep_decision_content_delivery(
    report: Mapping[str, Any],
    body: str,
) -> list[str]:
    """Fail closed when available analytics disappear from the visible DEEP body."""
    sections = {
        str(row.get("section_id") or "").upper(): dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    }
    text = str(body or "")
    upper = text.upper()
    failures: list[str] = []

    def content(section_id: str) -> dict[str, Any]:
        row = sections.get(section_id) or {}
        value = row.get("content")
        return dict(value or {}) if isinstance(value, Mapping) else {}

    def state(section_id: str) -> str:
        return str((sections.get(section_id) or {}).get("state") or "").upper()

    s14 = content("S14")
    routes = [
        dict(row) for row in s14.get("package_routes") or []
        if isinstance(row, Mapping)
    ]
    non_hold = [
        row for row in routes
        if str(row.get("route") or "").upper() != "HOLD"
    ]
    funded = [
        row for row in non_hold
        if max(
            len((row.get("moves") or {}).get("out") or []),
            len((row.get("moves") or {}).get("in") or []),
        ) >= 2
    ]
    mc = dict(s14.get("monte_carlo") or {})
    if state("S14") == "COMPLETE" and non_hold:
        for token, code in (
            ("OUT → IN", "FRONTIER_IDENTITIES_NOT_VISIBLE"),
            ("1GW", "FRONTIER_1GW_NOT_VISIBLE"),
            ("2GW", "FRONTIER_2GW_NOT_VISIBLE"),
            ("3GW", "FRONTIER_3GW_NOT_VISIBLE"),
            ("5GW", "FRONTIER_5GW_NOT_VISIBLE"),
            ("P>HOLD", "FRONTIER_PROBABILITY_NOT_VISIBLE"),
            ("Q10", "FRONTIER_DOWNSIDE_NOT_VISIBLE"),
            ("Q90", "FRONTIER_UPSIDE_NOT_VISIBLE"),
            ("BANK BEFORE", "FRONTIER_BANK_BEFORE_NOT_VISIBLE"),
            ("BANK AFTER", "FRONTIER_BANK_AFTER_NOT_VISIBLE"),
        ):
            if token not in upper:
                failures.append(code)
        if not any(str(row.get("route") or "").upper() == "HOLD" for row in routes):
            failures.append("HOLD_COMPARATOR_MISSING")
    if funded and "FUNDED / 2-TRANSFER" not in upper:
        failures.append("FUNDING_ROUTE_NOT_VISIBLE")
    if int(mc.get("actual_paths") or 0) >= 500_000:
        if "MC PATHS" not in upper:
            failures.append("MC_PATH_COUNT_NOT_VISIBLE")
        if "P>HOLD" not in upper or "Q10" not in upper or "Q90" not in upper:
            failures.append("MC_DISTRIBUTION_NOT_VISIBLE")

    for sid, expected, code in (
        ("S11", 20, "WATCHLIST20_VISIBLE_COUNT"),
        ("S12", 20, "RISE20_VISIBLE_COUNT"),
        ("S13", 20, "FALL20_VISIBLE_COUNT"),
    ):
        rows = list(content(sid).get("rows") or [])
        if state(sid) == "COMPLETE" and len(rows) != expected:
            failures.append(f"{code}={len(rows)}/{expected}")

    s15b = content("S15B")
    if state("S15B") == "COMPLETE":
        context = dict(s15b.get("current_league_context") or {})
        exposures = list(s15b.get("exposures") or [])
        if context.get("manager_count") and not exposures:
            failures.append("MINI_LEAGUE_PLACEHOLDER_ONLY")
        for token in ("LEAGUE LANDSCAPE:", "STARTER_COUNT", "CAPTAIN_COUNT", "VICE_COUNT", "EO_PCT"):
            if token not in upper:
                failures.append(f"MINI_LEAGUE_VISIBLE_FIELD_MISSING={token}")

    s16 = content("S16")
    rows16 = [
        dict(row) for row in s16.get("rows") or []
        if isinstance(row, Mapping)
    ]
    if state("S16") == "COMPLETE":
        if len(rows16) != 15:
            failures.append(f"ALL15_VISIBLE_COUNT={len(rows16)}/15")
        rich_keys = (
            "posterior_signal",
            "role_detail",
            "fixture_detail",
            "price_optionality",
            "mini_league_relevance",
        )
        for row in rows16:
            missing = [key for key in rich_keys if key not in row]
            if missing:
                failures.append(
                    "ALL15_DECISION_FIELDS_MISSING="
                    + str(row.get("element_id"))
                    + ":"
                    + ",".join(missing)
                )
                break
        if rows16 and "POSTERIOR" not in upper:
            failures.append("ALL15_POSTERIOR_NOT_VISIBLE")

    s16b = content("S16B")
    our15_post = [
        dict(row) for row in s16b.get("our15") or []
        if isinstance(row, Mapping)
    ]
    detailed_match_available = any(
        list((row.get("trajectory") or {}).get("matches") or [])
        for row in our15_post
    )
    if detailed_match_available:
        if "GW1→NOW" not in upper or "BAYESIAN UPDATE:" not in upper:
            failures.append("POST_MATCH_DETAIL_NOT_VISIBLE")
        if "- GW" not in upper:
            failures.append("POST_MATCH_ROWS_COLLAPSED")

    s06 = content("S06")
    if state("S06") == "COMPLETE" and s06.get("starting_xi"):
        for token in ("FORMATION:", "XI:", "BENCH:"):
            if token not in upper:
                failures.append(f"P1_7_NOT_VISIBLE={token}")
        if "CAPTAIN AUTHORITY:" not in upper:
            failures.append("P1_7_CAPTAIN_NOT_VISIBLE")

    s18 = content("S18")
    for key in (
        "NOW",
        "NEXT",
        "TRIGGER TO ACT",
        "LATEST SAFE DECISION POINT",
        "COST OF WAITING",
        "ABORT / REVERSAL",
    ):
        if key not in s18:
            failures.append(f"ACTION_BOARD_KEY_MISSING={key}")
    if routes and "BEST ALTERNATIVE" not in upper:
        failures.append("ACTION_BOARD_NOT_LINKED_TO_FRONTIER")

    # Fail closed when a COMPLETE decision-critical section is not explicitly
    # bound to its authoritative producer payload. This prevents presentation
    # code from silently reconstructing optimizer, Rank20, XI, mini-league,
    # ALL15, or post-match outputs.
    governed = ("S06", "S08", "S11", "S12", "S13", "S14", "S15B", "S16", "S16B")
    for sid in governed:
        if state(sid) != "COMPLETE":
            continue
        payload = content(sid)
        binding = dict(payload.get("authoritative_binding") or {})
        if str(binding.get("status") or "").upper() != "BOUND":
            failures.append(f"AUTHORITATIVE_PAYLOAD_NOT_BOUND={sid}")
        if not str(binding.get("producer") or "").strip():
            failures.append(f"AUTHORITATIVE_PRODUCER_MISSING={sid}")
        if not str(binding.get("payload_fingerprint") or "").strip():
            failures.append(f"AUTHORITATIVE_FINGERPRINT_MISSING={sid}")

    # Exact Rise/Fall20 must preserve the governed producer ordering and
    # direction. The real V6 predictor schema is order-authoritative and does
    # not carry an internal rank field; the renderer materializes visible
    # rank=1..20 from that deterministic order. Compact/legacy payloads retain
    # their producer-supplied rank aliases and are validated directly.
    for sid in ("S12", "S13"):
        if state(sid) != "COMPLETE":
            continue
        payload = content(sid)
        rows = [
            dict(row)
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        expected_direction = "RISE" if sid == "S12" else "FALL"
        adapter = str(payload.get("artifact_adapter") or "").upper()

        if adapter == "V6_DATA_PLAYERS_OFFSET0":
            expected_sort_contract = (
                "projected_percent DESC, id ASC"
                if sid == "S12"
                else "projected_percent ASC, id ASC"
            )
            if str(payload.get("sort_contract") or "") != expected_sort_contract:
                failures.append(
                    f"GOVERNED_RANK20_SORT_CONTRACT_MISMATCH={sid}"
                )
            sortable: list[tuple[float, int, int]] = []
            order_input_valid = True
            for index, row in enumerate(rows, start=1):
                try:
                    projected = float(row["projected_percent"])
                    element_id = int(row["element_id"])
                except (KeyError, TypeError, ValueError):
                    failures.append(
                        f"GOVERNED_RANK20_ORDER_INPUT_INVALID={sid}:{index}"
                    )
                    order_input_valid = False
                    break
                primary = -projected if sid == "S12" else projected
                sortable.append((primary, element_id, index))
            if order_input_valid:
                expected_indices = [
                    item[2]
                    for item in sorted(sortable, key=lambda item: (item[0], item[1]))
                ]
                if expected_indices != list(range(1, len(rows) + 1)):
                    mismatch = next(
                        (
                            index
                            for index, expected_index in enumerate(
                                expected_indices,
                                start=1,
                            )
                            if expected_index != index
                        ),
                        1,
                    )
                    failures.append(
                        f"GOVERNED_RANK20_ORDER_MISMATCH={sid}:{mismatch}"
                    )
        else:
            for index, row in enumerate(rows, start=1):
                governed_rank = (
                    row.get("rank")
                    if row.get("rank") is not None
                    else row.get("predictor_rank")
                    if row.get("predictor_rank") is not None
                    else row.get("direction_rank")
                )
                try:
                    rank_value = int(governed_rank)
                except (TypeError, ValueError):
                    rank_value = 0
                if rank_value != index:
                    failures.append(
                        f"GOVERNED_RANK20_RANK_MISMATCH={sid}:{index}"
                    )
                    break

        for index, row in enumerate(rows, start=1):
            if str(row.get("direction") or "").upper() != expected_direction:
                failures.append(
                    f"GOVERNED_RANK20_DIRECTION_MISMATCH={sid}:{index}"
                )
                break
            if not str(
                row.get("estimate_source") or row.get("source") or ""
            ).strip():
                failures.append(
                    f"GOVERNED_RANK20_SOURCE_MISSING={sid}:{index}"
                )
                break

    # Stage-A semantic cross-section invariants. These deliberately validate
    # meaning, not merely key presence, and cover the 36126675342 false-pass
    # class without hard-coding any player, GW, or route identity.
    s17 = content("S17")
    source_health = dict(s17.get("source_health") or {})
    bound_health = dict(s17.get("bound_authoritative_health") or {})
    bound_auth = str(bound_health.get("auth_state") or "").upper()
    visible_auth = str(
        source_health.get("authenticated_personal_scope") or ""
    ).upper()
    if bound_auth and bound_auth != "UNAVAILABLE" and visible_auth != bound_auth:
        failures.append(
            "S17_AUTH_CONTRADICTION="
            + visible_auth
            + "!="
            + bound_auth
        )

    s14b = content("S14B")
    ft_authority = dict(s14b.get("ft_authority") or {})
    ft_known = ft_authority.get("known") is True
    if not ft_known:
        ft_claims = [
            str(s14b.get("ft_saving_plan") or ""),
            str(s14b.get("order_of_transfers") or ""),
            *[
                str(row.get("planned_move") or "")
                for row in s14b.get("staging_rows") or []
                if isinstance(row, Mapping)
            ],
        ]
        if any(
            "SAVE FT" in claim.upper() or "ROLL FT" in claim.upper()
            for claim in ft_claims
        ):
            failures.append("FT_UNKNOWN_BUT_SAVE_OR_ROLL_CLAIMED")

    s06 = content("S06")
    if state("S06") == "COMPLETE":
        semantics = dict(s06.get("score_semantics") or {})
        required_score_tokens = (
            "XI_BASE_XPTS:",
            "CAPTAIN_ADJUSTED_XPTS:",
            "LINEUP_ROUTE_UTILITY:",
        )
        for token in required_score_tokens:
            if token not in upper:
                failures.append("S06_SCORE_SEMANTICS_NOT_VISIBLE=" + token)
        try:
            base = float(semantics["xi_base_xpts"])
            captain_value = float(semantics["captain_multiplier_value"])
            vice_value = float(semantics["vice_fallback_value"])
            derived = float(semantics["derived_captain_adjusted_xpts"])
            captain_adjusted = float(semantics["captain_adjusted_xpts"])
            route_utility = float(semantics["lineup_route_utility"])
        except (KeyError, TypeError, ValueError):
            failures.append("S06_SCORE_SEMANTICS_INCOMPLETE")
        else:
            expected_adjusted = base + captain_value + vice_value
            if abs(derived - expected_adjusted) > 1e-6:
                failures.append("S06_CAPTAIN_ADJUSTED_DERIVATION_MISMATCH")
            if abs(captain_adjusted - expected_adjusted) > 1e-6:
                failures.append("S06_SELECTED_FORMATION_SCORE_MISMATCH")
            # Route utility is intentionally a separate distributional objective.
            # Equality is allowed, but it may not be silently substituted for xPts.
            if not semantics.get("route_utility_definition"):
                failures.append("S06_ROUTE_UTILITY_SEMANTICS_MISSING")

    s14 = content("S14")
    if state("S14") == "COMPLETE":
        for token in (
            "FOOTBALL FRONTIER STATUS:",
            "EXECUTION ECONOMICS STATUS:",
            "EXECUTABLE",
        ):
            if token not in upper:
                failures.append("S14_ECONOMICS_NOT_VISIBLE=" + token)
        football_status = str(
            s14.get("football_frontier_status") or ""
        ).upper()
        economics_status = str(
            s14.get("execution_economics_status") or ""
        ).upper()
        if football_status != "COMPLETE":
            failures.append("S14_FOOTBALL_FRONTIER_FALSE_COMPLETE")
        if economics_status not in {"COMPLETE", "DEGRADED"}:
            failures.append("S14_EXECUTION_ECONOMICS_STATUS_MISSING")
        for route in s14.get("package_routes") or []:
            if not isinstance(route, Mapping):
                continue
            if str(route.get("route") or "").upper() == "HOLD":
                continue
            route_econ = str(
                route.get("execution_economics_status") or ""
            ).upper()
            executable = route.get("executable") is True
            if route_econ != "COMPLETE" and executable:
                failures.append(
                    "S14_DEGRADED_ECONOMICS_MARKED_EXECUTABLE="
                    + str(route.get("route") or "UNKNOWN")
                )
            if not executable and str(
                route.get("action_verdict") or ""
            ).upper() == "ACT":
                failures.append(
                    "S14_NONEXECUTABLE_ROUTE_MARKED_ACT="
                    + str(route.get("route") or "UNKNOWN")
                )

    for sid in ("S12", "S13"):
        payload = content(sid)
        freshness = str(payload.get("freshness_state") or "").upper()
        if freshness == "STALE" and state(sid) == "COMPLETE":
            failures.append(f"{sid}_STALE_PRICE_MARKED_COMPLETE")
        for index, row in enumerate(payload.get("rows") or [], start=1):
            if not isinstance(row, Mapping):
                continue
            row_freshness = str(
                row.get("freshness_state") or freshness or ""
            ).upper()
            if row_freshness == "STALE" and str(
                row.get("source_age_seconds") or ""
            ) == "":
                failures.append(f"{sid}_STALE_WITHOUT_SOURCE_AGE={index}")

    s10 = content("S10")
    radar_freshness = str(s10.get("freshness_state") or "").upper()
    for index, row in enumerate(s10.get("rows") or [], start=1):
        if not isinstance(row, Mapping):
            continue
        row_freshness = str(
            row.get("freshness_state") or radar_freshness or ""
        ).upper()
        if row_freshness == "STALE" and "STALE PREDICTOR" not in str(
            row.get("decision_implication") or ""
        ).upper():
            failures.append(
                f"S10_STALE_PRICE_LOOKS_LIVE={index}"
            )

    # Watchlist20 remains a football-decision surface: exact 5/5/5/5 by pos.
    if state("S11") == "COMPLETE":
        rows = [dict(row) for row in content("S11").get("rows") or [] if isinstance(row, Mapping)]
        counts: dict[str, int] = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for row in rows:
            pos = str(row.get("position") or "").upper()
            if pos in counts:
                counts[pos] += 1
        if counts != {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}:
            failures.append("WATCHLIST20_POSITION_BALANCE=" + str(counts))

    return list(dict.fromkeys(failures))
