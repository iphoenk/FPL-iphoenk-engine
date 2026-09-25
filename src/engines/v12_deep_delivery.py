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


    # Stage-A semantic correctness barrier. COMPLETE sections must expose
    # explicit producer authority. Missing authority is itself a semantic
    # failure; no guessed aliases are accepted.
    s17 = content("S17")
    if state("S17") == "COMPLETE":
        authority = s17.get("authority")
        if not isinstance(authority, Mapping):
            failures.append("S17_AUTH_AUTHORITY_MISSING")
        else:
            bound_auth = str(authority.get("personal_auth_state") or "").upper()
            if not bound_auth:
                failures.append("S17_AUTH_AUTHORITY_MISSING")
            visible_auth = str(
                (s17.get("source_health") or {}).get("authenticated_personal_scope")
                or ""
            ).upper()
            if not visible_auth:
                failures.append("S17_AUTH_VISIBLE_STATE_MISSING")
            elif bound_auth and visible_auth != bound_auth:
                failures.append(
                    "S17_AUTH_CONTRADICTION="
                    + bound_auth + "!=" + visible_auth
                )

    s14b = content("S14B")
    if state("S14B") == "COMPLETE":
        ft_authority = s14b.get("ft_authority")
        if not isinstance(ft_authority, Mapping):
            failures.append("S14B_FT_AUTHORITY_MISSING")
        else:
            ft_known = ft_authority.get("known") is True
            staging_text = str({
                "staging_rows": s14b.get("staging_rows"),
                "ft_saving_plan": s14b.get("ft_saving_plan"),
                "order_of_transfers": s14b.get("order_of_transfers"),
            }).upper()
            if not ft_known and ("SAVE FT" in staging_text or "ROLL FT" in staging_text):
                failures.append("S14B_FT_CLAIM_WITHOUT_AUTHORITY")

    if state("S14") == "COMPLETE":
        for route in non_hold:
            transfer_cost = route.get("transfer_cost")
            if not isinstance(transfer_cost, Mapping):
                failures.append(
                    "S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING="
                    + str(route.get("route") or "UNKNOWN")
                )
                break
            route_econ = str(route.get("execution_economics_status") or "").upper()
            if not route_econ:
                failures.append(
                    "S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING="
                    + str(route.get("route") or "UNKNOWN")
                )
                break
            executable = route.get("executable")
            if executable is None:
                failures.append(
                    "S14_EXECUTABLE_STATE_MISSING="
                    + str(route.get("route") or "UNKNOWN")
                )
                break
            if route_econ != "AVAILABLE" and executable is True:
                failures.append(
                    "S14_EXECUTABLE_WITHOUT_FINANCE="
                    + str(route.get("route") or "UNKNOWN")
                )
                break

    for sid in ("S10", "S12", "S13"):
        if state(sid) != "COMPLETE":
            continue
        for index, row in enumerate(content(sid).get("rows") or [], start=1):
            if not isinstance(row, Mapping):
                continue
            if sid in {"S12", "S13"}:
                date_state = str(row.get("date_state") or "").upper()
                if date_state not in {
                    "EXPECTED_CHANGE_DATE",
                    "NO_CROSSING_WITHIN_GOVERNED_HORIZON",
                    "DATE_UNAVAILABLE",
                }:
                    failures.append(f"{sid}_TERMINAL_DATE_STATE_MISSING={index}")
                    break
            if "evidence_timestamp" not in row:
                failures.append(f"{sid}_PRICE_EVIDENCE_TIMESTAMP_MISSING={index}")
                break

    if state("S06") == "COMPLETE":
        semantics = s06.get("score_semantics")
        if not isinstance(semantics, Mapping):
            failures.append("S06_SCORE_SEMANTICS_MISSING")
        else:
            required_semantics = {
                "lineup_score.xpts_mean": "XI_BASE_XPTS",
                "lineup_score.robust": "LINEUP_ROUTE_UTILITY",
                "formation_comparison[].expected_fpl_points_with_captain_vice": "CAPTAIN_ADJUSTED_XPTS",
                "formation_comparison[].route_utility": "LINEUP_ROUTE_UTILITY",
            }
            for key, expected in required_semantics.items():
                if str(semantics.get(key) or "") != expected:
                    failures.append("S06_SCORE_SEMANTICS_INVALID=" + key)
                    break

    return list(dict.fromkeys(failures))
