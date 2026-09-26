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
    governed = ("S06", "S08", "S11", "S12", "S13", "S14", "S15B", "S16", "S16B", "S19")
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

    # Stage-B Watchlist contract: Scanner20 is exact 5/5/5/5 when COMPLETE;
    # Actionable Watchlist is a gated, unpadded subset and never owns ACT.
    if state("S11") == "COMPLETE":
        s11 = content("S11")
        rows = [
            dict(row)
            for row in s11.get("scanner20") or s11.get("rows") or []
            if isinstance(row, Mapping)
        ]
        counts: dict[str, int] = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        ids: list[int] = []
        expected_formula = {
            "GK": "V12_WATCH_GK_EVIDENCE_V1",
            "DEF": "V12_WATCH_DEF_EVIDENCE_V1",
            "MID": "V12_WATCH_MID_EVIDENCE_V1",
            "FWD": "V12_WATCH_FWD_EVIDENCE_V1",
        }
        for index, row in enumerate(rows, start=1):
            pos = str(row.get("position") or "").upper()
            if pos in counts:
                counts[pos] += 1
            try:
                ids.append(int(row.get("element_id") or row.get("element")))
            except (TypeError, ValueError):
                failures.append(f"WATCHLIST20_ELEMENT_ID_INVALID={index}")
            family = dict(row.get("position_specific_evidence") or {})
            if str(family.get("formula_id") or "") != expected_formula.get(pos):
                failures.append(f"WATCHLIST_POSITION_FORMULA_MISSING={index}:{pos}")
            if pos == "GK" and family.get("attacker_xgi_gate_required") is not False:
                failures.append("WATCHLIST_GK_ATTACKER_XGI_GATE_FORBIDDEN")
            gate = dict(row.get("admission_gate") or {})
            if "admitted" not in gate or not isinstance(gate.get("checks"), Mapping):
                failures.append(f"WATCHLIST_ADMISSION_GATE_MISSING={index}")
        if counts != {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}:
            failures.append("WATCHLIST20_POSITION_BALANCE=" + str(counts))
        if len(ids) != len(set(ids)):
            failures.append("WATCHLIST20_DUPLICATE_ELEMENT")
        owned_ids = {
            int(row.get("element_id") or row.get("element"))
            for row in content("S02").get("rows") or []
            if isinstance(row, Mapping)
            and (row.get("element_id") is not None or row.get("element") is not None)
        }
        if owned_ids & set(ids):
            failures.append("WATCHLIST20_OWNED_PLAYER_INCLUDED")
        actionable = [
            dict(row)
            for row in s11.get("actionable_watchlist") or []
            if isinstance(row, Mapping)
        ]
        actionable_ids = {
            int(row.get("element_id") or row.get("element") or 0)
            for row in actionable
            if int(row.get("element_id") or row.get("element") or 0) > 0
        }
        if not actionable_ids.issubset(set(ids)):
            failures.append("ACTIONABLE_WATCHLIST_NOT_SUBSET_OF_SCANNER20")
        if len(actionable_ids) != len(actionable):
            failures.append("ACTIONABLE_WATCHLIST_DUPLICATE_ELEMENT")
        for index, row in enumerate(actionable, start=1):
            if (row.get("admission_gate") or {}).get("admitted") is not True:
                failures.append(f"ACTIONABLE_WATCHLIST_UNADMITTED={index}")
            action = str(row.get("action") or row.get("watchlist_action") or "").upper()
            if action == "ACT":
                failures.append(f"WATCHLIST_EMITS_ACT={index}")
        if s11.get("actionable_watchlist_is_unpadded_subset") is not True:
            failures.append("ACTIONABLE_WATCHLIST_PADDING_CONTRACT_MISSING")
        if s11.get("price_is_overlay_not_primary_authority") is not True:
            failures.append("WATCHLIST_PRICE_PRIMARY_AUTHORITY")
        if "POSITIONAL SCANNER20" not in upper or "ACTIONABLE WATCHLIST" not in upper:
            failures.append("WATCHLIST_TWO_SURFACES_NOT_VISIBLE")

    # Stage-B calendar/workload/travel/weather contract. It is descriptive
    # evidence only and may feed P1.1 review; it never owns a fatigue model.
    if state("S05") in {"COMPLETE", "DEGRADED"}:
        s05 = content("S05")
        topology = str(s05.get("gw_topology") or "")
        allowed_topology = {
            "NORMAL_GW",
            "DOUBLE_GW",
            "BLANK_GW",
            "MIXED_DGW_BGW",
            "REARRANGED_FIXTURE",
            "INTERNATIONAL_BREAK",
            "NORMAL_WITH_MIDWEEK_COMPETITION",
            "CONGESTED_PERIOD",
        }
        if topology not in allowed_topology:
            failures.append("S05_GW_TOPOLOGY_MISSING_OR_INVALID")
        coverage = dict(s05.get("competition_coverage") or {})
        if not coverage:
            failures.append("S05_COMPETITION_COVERAGE_MISSING")
        if state("S05") == "COMPLETE" and coverage.get("verified_non_pl_schedule_bound") is not True:
            failures.append("S05_COMPLETE_WITHOUT_NON_PL_SCHEDULE_AUTHORITY")
        if s05.get("workload_feeds_p1_1_review_only") is not True:
            failures.append("S05_WORKLOAD_MODEL_BOUNDARY_MISSING")
        if s05.get("static_fatigue_penalty_applied") is not False:
            failures.append("S05_UNGOVERNED_FATIGUE_PENALTY")
        if s05.get("weather_mutates_football_model") is not False:
            failures.append("S05_WEATHER_MUTATES_FOOTBALL_MODEL")
        if s05.get("dgw_cross_fixture_covariance_claimed") is not False:
            failures.append("S05_UNSUPPORTED_DGW_COVARIANCE")
        workload = [
            dict(row)
            for row in s05.get("player_workload") or []
            if isinstance(row, Mapping)
        ]
        for index, row in enumerate(workload, start=1):
            gw_state = str(row.get("gw_state") or "").upper()
            fixtures = [
                item
                for item in row.get("planning_gw_fixtures") or []
                if isinstance(item, Mapping)
            ]
            if gw_state == "DOUBLE" and len(fixtures) < 2:
                failures.append(f"S05_DGW_FIXTURE_DETAIL_MISSING={index}")
            if gw_state == "BLANK" and fixtures:
                failures.append(f"S05_BGW_PLAYER_HAS_FIXTURE={index}")
        for index, row in enumerate(s05.get("weather") or [], start=1):
            if not isinstance(row, Mapping):
                continue
            impact = str(row.get("fpl_impact") or "UNAVAILABLE").upper()
            if impact not in {"NORMAL", "LOW", "MATERIAL", "UNAVAILABLE"}:
                failures.append(f"S05_WEATHER_IMPACT_INVALID={index}")
            if impact != "UNAVAILABLE" and not row.get("evidence_timestamp"):
                failures.append(f"S05_WEATHER_TIMESTAMP_MISSING={index}")
        for token in ("GW TOPOLOGY:", "PLAYER WORKLOAD / TRAVEL", "### WEATHER"):
            if token not in upper:
                failures.append(f"S05_VISIBLE_CONTRACT_MISSING={token}")
        if any(str(row.get("gw_state") or "").upper() == "BLANK" for row in workload):
            if "BLANK" not in upper:
                failures.append("S05_BGW_NOT_VISIBLE")

        blank_team_ids = sorted(
            int(value)
            for value in (s05.get("period_flags") or {}).get("blank_gw_teams") or []
        )
        bgw_active = bool(blank_team_ids) or topology in {"BLANK_GW", "MIXED_DGW_BGW"}
        if bgw_active:
            current15_ids = {
                int(row.get("element_id") or row.get("element"))
                for row in content("S02").get("rows") or []
                if isinstance(row, Mapping)
                and (row.get("element_id") is not None or row.get("element") is not None)
            }
            expected_blank_owned = sorted(
                int(row.get("element_id"))
                for row in workload
                if row.get("element_id") is not None
                and int(row.get("element_id")) in current15_ids
                and str(row.get("gw_state") or "").upper() == "BLANK"
            )
            final_judgement = dict(content("S19").get("final_judgement") or {})
            propagation = {
                "S06": dict(content("S06").get("bgw_context") or {}),
                "S09": dict(content("S09").get("bgw_context") or {}),
                "S14": dict(content("S14").get("bgw_context") or {}),
                "S14B": dict(content("S14B").get("bgw_context") or {}),
                "S19": dict(final_judgement.get("bgw_context") or {}),
            }
            for sid, context in propagation.items():
                try:
                    context_blank_teams = sorted(
                        int(value) for value in context.get("blank_team_ids") or []
                    )
                    context_blank_owned = sorted(
                        int(value)
                        for value in context.get("blank_owned_element_ids") or []
                    )
                except (TypeError, ValueError):
                    context_blank_teams = []
                    context_blank_owned = []
                if (
                    context.get("source_section") != "S05"
                    or context.get("active") is not True
                    or context.get("decision_math_mutated") is not False
                    or context.get("context_only") is not True
                    or context.get("gw_topology") != topology
                    or context_blank_teams != blank_team_ids
                    or context_blank_owned != expected_blank_owned
                ):
                    failures.append(f"S05_BGW_NOT_PROPAGATED_{sid}")
            if content("S06").get("bgw_lineup_review_required") is not True:
                failures.append("S05_BGW_S06_REVIEW_MISSING")
            if content("S09").get("bgw_chip_review_required") is not True:
                failures.append("S05_BGW_S09_CHIP_REVIEW_MISSING")
            if (
                content("S14").get("bgw_frontier_review_required") is not True
                or content("S14").get("bgw_is_context_not_second_optimizer") is not True
            ):
                failures.append("S05_BGW_S14_FRONTIER_REVIEW_MISSING")
            if content("S14B").get("bgw_reoptimization_trigger") is not True:
                failures.append("S05_BGW_S14B_REOPTIMIZE_MISSING")
            if final_judgement.get("bgw_reconciled") is not True:
                failures.append("S05_BGW_S19_RECONCILIATION_MISSING")


    # Stage-C captain / mini-league / final-judgement semantic barrier.
    # Football baseline remains P1.7; mini-league is a downstream exposure
    # overlay and must not manufacture captain candidates outside final XI.
    current15_ids = {
        int(row.get("element_id") or row.get("element"))
        for row in content("S02").get("rows") or []
        if isinstance(row, Mapping)
        and (row.get("element_id") is not None or row.get("element") is not None)
    }
    final_xi_ids = {
        int(
            row.get("element")
            if isinstance(row, Mapping)
            else row
        )
        for row in content("S06").get("starting_xi") or []
        if (
            (isinstance(row, Mapping) and row.get("element") is not None)
            or (not isinstance(row, Mapping) and row is not None)
        )
    }

    s08 = content("S08")
    if state("S08") == "COMPLETE":
        captain_state = str(s08.get("decision_state") or "").upper()
        if captain_state not in {"WAIT", "PREPARE", "LOCK"}:
            failures.append("S08_CAPTAIN_DECISION_STATE_INVALID")
        cap = dict(s08.get("captain") or {})
        vice = dict(s08.get("vice_captain") or {})
        try:
            cap_id = int(cap.get("element_id"))
        except (TypeError, ValueError):
            cap_id = 0
        try:
            vice_id = int(vice.get("element_id"))
        except (TypeError, ValueError):
            vice_id = 0
        if cap_id <= 0 or cap_id not in current15_ids:
            failures.append("S08_CAPTAIN_NOT_IN_CURRENT15")
        if vice_id <= 0 or vice_id not in current15_ids:
            failures.append("S08_VICE_NOT_IN_CURRENT15")
        if cap_id <= 0 or cap_id not in final_xi_ids:
            failures.append("S08_CAPTAIN_NOT_IN_FINAL_XI")
        if vice_id <= 0 or vice_id not in final_xi_ids:
            failures.append("S08_VICE_NOT_IN_FINAL_XI")
        if cap_id > 0 and cap_id == vice_id:
            failures.append("S08_CAPTAIN_EQUALS_VICE")

        proof = dict(s08.get("candidate_universe_proof") or {})
        for key in (
            "captain_in_current15",
            "vice_in_current15",
            "captain_in_final_xi",
            "vice_in_final_xi",
            "captain_vice_distinct",
            "frontier_subset_of_final_xi",
        ):
            if proof.get(key) is not True:
                failures.append(f"S08_LEGALITY_PROOF_FAIL={key}")

        frontier = [
            dict(row)
            for row in s08.get("captain_frontier") or []
            if isinstance(row, Mapping)
        ]
        if not frontier:
            failures.append("S08_CAPTAIN_FRONTIER_MISSING")
        for index, row in enumerate(frontier, start=1):
            try:
                element = int(row.get("element_id"))
            except (TypeError, ValueError):
                element = 0
            if element <= 0 or element not in final_xi_ids:
                failures.append(f"S08_FRONTIER_OUTSIDE_FINAL_XI={index}")
            for scope_key in ("league_scope", "rivals_scope", "direct_scope"):
                if not isinstance(row.get(scope_key), Mapping):
                    failures.append(f"S08_CAPTAIN_SCOPE_MISSING={index}:{scope_key}")
            if not str(row.get("exposure_leverage_class") or ""):
                failures.append(f"S08_EXPOSURE_LEVERAGE_CLASS_MISSING={index}")
            if "expected_rank_utility" in row:
                failures.append(f"S08_CATEGORICAL_RANK_UTILITY_FORBIDDEN={index}")
        if s08.get("football_baseline_first") is not True:
            failures.append("S08_FOOTBALL_BASELINE_ORDER_MISSING")
        if s08.get("mini_league_overlay_second") is not True:
            failures.append("S08_MINI_LEAGUE_OVERLAY_ORDER_MISSING")
        if "OWNED FINAL-XI CAPTAIN FRONTIER" not in upper:
            failures.append("S08_CAPTAIN_FRONTIER_NOT_VISIBLE")
        if "EXPOSURE / LEVERAGE CLASS" not in upper:
            failures.append("S08_EXPOSURE_CLASS_NOT_VISIBLE")

    s15b = content("S15B")
    if state("S15B") == "COMPLETE":
        scopes = dict(s15b.get("denominator_scopes") or {})
        league_scope = dict(scopes.get("LEAGUE") or {})
        rivals_scope = dict(scopes.get("RIVALS") or {})
        direct_scope = dict(scopes.get("DIRECT") or {})
        if league_scope.get("includes_us") is not True:
            failures.append("S15B_LEAGUE_SCOPE_MUST_INCLUDE_US")
        if rivals_scope.get("includes_us") is not False:
            failures.append("S15B_RIVALS_SCOPE_MUST_EXCLUDE_US")
        if direct_scope.get("includes_us") is not False:
            failures.append("S15B_DIRECT_SCOPE_MUST_EXCLUDE_US")
        try:
            league_expected = int(league_scope.get("expected"))
            rivals_expected = int(rivals_scope.get("expected"))
        except (TypeError, ValueError):
            league_expected = rivals_expected = -1
        if league_expected <= 0 or rivals_expected != max(0, league_expected - 1):
            failures.append("S15B_LEAGUE_RIVALS_DENOMINATOR_RELATION_INVALID")
        if (
            league_expected > 0
            and str(league_scope.get("label") or "")
            != f"LEAGUE{league_expected}_INCL_US"
        ):
            failures.append("S15B_LEAGUE_SCOPE_LABEL_INVALID")
        if (
            rivals_expected >= 0
            and str(rivals_scope.get("label") or "")
            != f"RIVALS{rivals_expected}_EXCL_US"
        ):
            failures.append("S15B_RIVALS_SCOPE_LABEL_INVALID")
        if str(s15b.get("disclosed_picks_label") or "") != "BEHAVIOURAL BASELINE":
            failures.append("S15B_BEHAVIOURAL_BASELINE_LABEL_MISSING")

        for scope_key, payload_key in (
            ("LEAGUE", "league_our15_exposure"),
            ("RIVALS", "rivals_our15_exposure"),
            ("DIRECT", "direct_rival_our15_exposure"),
        ):
            scope = dict(scopes.get(scope_key) or {})
            rows = [
                dict(row)
                for row in s15b.get(payload_key) or []
                if isinstance(row, Mapping)
            ]
            if len(rows) != 15:
                failures.append(f"S15B_OUR15_SCOPE_COUNT={scope_key}:{len(rows)}/15")
            denominator = scope.get("denominator")
            for index, row in enumerate(rows, start=1):
                if row.get("denominator") != denominator:
                    failures.append(
                        f"S15B_DENOMINATOR_MISMATCH={scope_key}:{index}"
                    )
                    break
                if row.get("eo_pct") is not None:
                    if row.get("eo_supported") is not True:
                        failures.append(
                            f"S15B_UNSUPPORTED_EO={scope_key}:{index}"
                        )
                        break
                    if row.get("effective_multiplier_sum") is None:
                        failures.append(
                            f"S15B_EO_UNITS_MISSING={scope_key}:{index}"
                        )
                        break

        direct_meta = dict(s15b.get("direct_rival_scope") or {})
        if direct_meta.get("denominator") != direct_scope.get("denominator"):
            failures.append("S15B_DIRECT_DENOMINATOR_MISLABEL")
        try:
            direct_requested = int(direct_meta.get("requested_above_count"))
            direct_standings = int(direct_meta.get("standings_rival_count"))
            direct_picks = int(direct_meta.get("picks_available_count"))
            direct_expected = int(direct_scope.get("expected"))
            direct_collected = int(direct_scope.get("collected"))
            direct_denominator = int(direct_scope.get("denominator"))
        except (TypeError, ValueError):
            direct_requested = direct_standings = direct_picks = -1
            direct_expected = direct_collected = direct_denominator = -1
        if direct_requested <= 0:
            failures.append("S15B_DIRECT_REQUESTED_COHORT_MISSING")
        else:
            expected_direct_label = f"DIRECT{direct_requested}_ABOVE_US"
            if str(direct_scope.get("label") or "") != expected_direct_label:
                failures.append("S15B_DIRECT_SCOPE_LABEL_INVALID")
        if (
            direct_standings < 0
            or direct_picks < 0
            or direct_expected != direct_standings
            or direct_collected != direct_picks
            or direct_denominator != direct_picks
            or (
                direct_requested > 0
                and direct_standings > direct_requested
            )
        ):
            failures.append("S15B_DIRECT_SCOPE_COHORT_RELATION_INVALID")
        for index, rival in enumerate(s15b.get("direct_rivals") or [], start=1):
            if not isinstance(rival, Mapping):
                continue
            for key in (
                "xi_overlap_count",
                "bench_overlap_count",
                "shields",
                "rival_only_threats",
                "differential_against_us",
            ):
                if key not in rival:
                    failures.append(f"S15B_DIRECT_RIVAL_DETAIL_MISSING={index}:{key}")
        if "expected_rank_utility" in str(s15b):
            failures.append("S15B_CATEGORICAL_RANK_UTILITY_FORBIDDEN")
        posture = str(
            (s15b.get("strategy_implication") or {}).get("human_posture")
            or ""
        ).upper()
        if posture not in {
            "PROTECT",
            "BALANCED",
            "CHASE_MODERATE",
            "CHASE_AGGRESSIVE",
        }:
            failures.append("S15B_POSTURE_INVALID")
        for token in (
            "DENOMINATOR SCOPES",
            "BEHAVIOURAL BASELINE",
            "EXPOSURE / LEVERAGE CLASS",
        ):
            if token not in upper:
                failures.append(f"S15B_VISIBLE_CONTRACT_MISSING={token}")

    s19 = content("S19")
    if state("S19") == "COMPLETE":
        judgement = dict(s19.get("final_judgement") or {})
        consumed = {
            str(value)
            for value in judgement.get("consumed_sections") or []
        }
        if not {"S08", "S15B"}.issubset(consumed):
            failures.append("S19_DID_NOT_CONSUME_S08_S15B")
        final_cap = dict(judgement.get("final_captain") or {})
        final_vice = dict(judgement.get("vice") or {})
        try:
            final_cap_id = int(final_cap.get("element_id"))
        except (TypeError, ValueError):
            final_cap_id = 0
        try:
            final_vice_id = int(final_vice.get("element_id"))
        except (TypeError, ValueError):
            final_vice_id = 0
        if final_cap_id not in current15_ids or final_cap_id not in final_xi_ids:
            failures.append("S19_CAPTAIN_NOT_IN_CURRENT15_FINAL_XI")
        if final_vice_id not in current15_ids or final_vice_id not in final_xi_ids:
            failures.append("S19_VICE_NOT_IN_CURRENT15_FINAL_XI")
        if final_cap_id > 0 and final_cap_id == final_vice_id:
            failures.append("S19_CAPTAIN_EQUALS_VICE")
        s08_cap_id = 0
        s08_vice_id = 0
        try:
            s08_cap_id = int((s08.get("captain") or {}).get("element_id"))
            s08_vice_id = int((s08.get("vice_captain") or {}).get("element_id"))
        except (TypeError, ValueError):
            pass
        if (
            (final_cap_id != s08_cap_id or final_vice_id != s08_vice_id)
            and not str(judgement.get("reconciliation_reason") or "").strip()
        ):
            failures.append("S19_S08_CONTRADICTION_WITHOUT_RECONCILIATION")
        if (
            str(judgement.get("captain_state") or "").upper()
            != str(s08.get("decision_state") or "").upper()
        ):
            failures.append("S19_CAPTAIN_STATE_CONTRADICTS_S08")
        if "S19 CONSUMED:" not in upper or "RECONCILIATION:" not in upper:
            failures.append("S19_RECONCILIATION_NOT_VISIBLE")

    # Stage-A semantic correctness barrier. Field paths below are the exact
    # section payload contract emitted by v12_integrated_report_runner; a
    # COMPLETE section with missing authority is itself a semantic failure.
    s17 = content("S17")
    if state("S17") == "COMPLETE":
        source_health = dict(s17.get("source_health") or {})
        auth_authority = dict(s17.get("auth_authority") or {})
        if not auth_authority.get("field") or "value" not in auth_authority:
            failures.append("S17_AUTH_AUTHORITY_MISSING")
        private_auth = str(source_health.get("private_auth_state") or "").upper()
        visible_auth = str(source_health.get("authenticated_personal_scope") or "").upper()
        authority_value = str(auth_authority.get("value") or "").upper()
        if not private_auth:
            failures.append("S17_PRIVATE_AUTH_STATE_MISSING")
        if authority_value and private_auth and authority_value != private_auth:
            failures.append("S17_AUTH_AUTHORITY_VALUE_MISMATCH")
        if private_auth and visible_auth and private_auth != visible_auth:
            failures.append("S17_AUTH_CONTRADICTION")
        price_health = str(source_health.get("price_predictor") or "").upper()
        price_freshness = str(
            source_health.get("price_predictor_freshness") or ""
        ).upper()
        price_age = source_health.get("price_predictor_source_age_minutes")
        if price_health not in {"", "UNAVAILABLE"}:
            if price_freshness not in {"FRESH", "STALE"} or price_age is None:
                failures.append("S17_PRICE_FRESHNESS_AUTHORITY_MISSING")

    s14b = content("S14B")
    if state("S14B") == "COMPLETE":
        ft_authority = dict(s14b.get("ft_authority") or {})
        if "known" not in ft_authority or not ft_authority.get("source"):
            failures.append("S14B_FT_AUTHORITY_MISSING")
        ft_status = str(s14b.get("free_transfers_status") or "").upper()
        if not ft_status:
            failures.append("S14B_FT_STATUS_MISSING")
        ft_known = bool(
            ft_authority.get("known") is True
            and isinstance(s14b.get("free_transfers"), int)
            and ft_status not in {
                "", "UNAVAILABLE", "UNKNOWN", "NOT_SUPPORTED",
                "STALE_NOT_AUTHORIZED", "AUTH_EXPIRED",
            }
        )
        staging_text = str(s14b).upper()
        if not ft_known and ("SAVE FT" in staging_text or "ROLL FT" in staging_text):
            failures.append("S14B_FT_CLAIM_WITHOUT_AUTHORITY")

    if state("S14") == "COMPLETE":
        economics_authority = dict(s14.get("execution_economics_authority") or {})
        economics_status = str(s14.get("execution_economics_status") or "").upper()
        if not economics_authority:
            failures.append("S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING")
        if not economics_status:
            failures.append("S14_EXECUTION_ECONOMICS_STATUS_MISSING")
        for route in non_hold:
            route_id = str(route.get("route") or "UNKNOWN")
            route_status = str(route.get("execution_economics_status") or "").upper()
            if not route_status or "executable" not in route:
                failures.append("S14_ROUTE_EXECUTION_STATE_MISSING=" + route_id)
                continue
            if (
                economics_status != "AVAILABLE"
                or route_status != "AVAILABLE"
            ) and route.get("executable") is not False:
                failures.append("S14_EXECUTABLE_WITHOUT_FINANCE=" + route_id)

    for sid in ("S10", "S12", "S13"):
        if state(sid) != "COMPLETE":
            continue
        rows = [
            dict(row)
            for row in content(sid).get("rows") or []
            if isinstance(row, Mapping)
        ]
        for index, row in enumerate(rows, start=1):
            freshness = str(row.get("freshness") or "").upper()
            if freshness not in {"FRESH", "STALE"} or row.get("source_age_minutes") is None:
                failures.append(f"{sid}_PRICE_FRESHNESS_AUTHORITY_MISSING={index}")
                break
            if sid in {"S12", "S13"}:
                date_state = str(row.get("date_state") or "").upper()
                if row.get("date_state_complete") is not True or date_state not in {
                    "EXPECTED_CHANGE_DATE",
                    "NO_CROSSING_WITHIN_GOVERNED_HORIZON",
                    "DATE_UNAVAILABLE",
                }:
                    failures.append(f"{sid}_TERMINAL_DATE_STATE_MISSING={index}")
                    break
        if rows:
            if "SOURCE_AGE_MINUTES" not in upper:
                failures.append(f"{sid}_PRICE_SOURCE_AGE_NOT_VISIBLE")
            if "FRESHNESS" not in upper:
                failures.append(f"{sid}_PRICE_FRESHNESS_NOT_VISIBLE")
            s17_freshness = str(
                (content("S17").get("source_health") or {}).get(
                    "price_predictor_freshness"
                )
                or ""
            ).upper()
            row_freshness = str(rows[0].get("freshness") or "").upper()
            if (
                state("S17") == "COMPLETE"
                and s17_freshness
                and row_freshness
                and s17_freshness != row_freshness
            ):
                failures.append(f"{sid}_S17_PRICE_FRESHNESS_CONTRADICTION")

    if state("S06") == "COMPLETE":
        semantics = dict(s06.get("score_semantics") or {})
        if str(semantics.get("authority") or "") != "P1_7_LINEUP":
            failures.append("S06_SCORE_SEMANTICS_AUTHORITY_MISSING")
        base = s06.get("xi_base_xpts")
        captain_adjusted = s06.get("captain_adjusted_xpts")
        if base is None or captain_adjusted is None:
            failures.append("S06_SCORE_VALUES_MISSING")
        else:
            try:
                mismatch = abs(float(base) - float(captain_adjusted)) > 1e-9
            except (TypeError, ValueError):
                mismatch = False
            if mismatch and str(semantics.get("relationship") or "").upper() != "DISTINCT_BY_DESIGN":
                failures.append("S06_AMBIGUOUS_SCORE_SEMANTICS")

    return list(dict.fromkeys(failures))
