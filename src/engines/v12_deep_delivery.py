from __future__ import annotations

"""Report-plane delivery guards for V12 DEEP.

This module never computes football projections, Monte Carlo paths, package
utility, mini-league exposure, or transfer economics. It only reconciles
already-produced personal evidence and validates that authoritative V12
analytics are materially visible in the DEEP report.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence


from src.engines.v12_competitive_window import resolve_competitive_window

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
        scopes = dict(s15b.get("denominator_scopes") or {})
        league_scope = dict(scopes.get("LEAGUE") or {})
        rivals_scope = dict(scopes.get("RIVALS") or {})
        competitive_scope = dict(scopes.get("COMPETITIVE") or {})
        if league_scope.get("includes_us") is not True:
            failures.append("S15B_LEAGUE_SCOPE_MUST_INCLUDE_US")
        if rivals_scope.get("includes_us") is not False:
            failures.append("S15B_RIVALS_SCOPE_MUST_EXCLUDE_US")
        if competitive_scope.get("includes_us") is not False:
            failures.append("S15B_COMPETITIVE_SCOPE_MUST_EXCLUDE_US")
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
        if str(competitive_scope.get("label") or "") != "COMPETITIVE_WINDOW":
            failures.append("S15B_COMPETITIVE_SCOPE_LABEL_INVALID")
        if str(s15b.get("disclosed_picks_label") or "") != "BEHAVIOURAL BASELINE":
            failures.append("S15B_BEHAVIOURAL_BASELINE_LABEL_MISSING")

        full_composition = [
            dict(row)
            for row in s15b.get("league_full_composition") or []
            if isinstance(row, Mapping)
        ]
        if s15b.get("league_full_composition_complete") is not True:
            failures.append("S15B_FULL_LEAGUE_COMPOSITION_NOT_COMPLETE")
        if not full_composition:
            failures.append("S15B_FULL_LEAGUE_COMPOSITION_MISSING")
        else:
            denominator = league_scope.get("denominator")
            expected_slots = (
                int(denominator) * 15
                if isinstance(denominator, int) and denominator > 0
                else None
            )
            owned_slots = sum(
                int(row.get("ownership_count") or 0)
                for row in full_composition
            )
            if expected_slots is not None and owned_slots != expected_slots:
                failures.append(
                    f"S15B_FULL_LEAGUE_SLOT_COUNT={owned_slots}/{expected_slots}"
                )
            required = {
                "ownership_count", "ownership_pct", "starter_count", "starter_pct",
                "bench_count", "bench_pct", "captain_count", "vice_count", "position"
            }
            for index, row in enumerate(full_composition, start=1):
                missing = sorted(key for key in required if key not in row)
                if missing:
                    failures.append(
                        f"S15B_FULL_LEAGUE_ROW_MISSING={index}:{','.join(missing)}"
                    )
                    break
        if "FULL ICON+ COMPOSITION" not in upper:
            failures.append("S15B_FULL_LEAGUE_COMPOSITION_NOT_VISIBLE")

        for scope_key, payload_key in (
            ("LEAGUE", "league_our15_exposure"),
            ("RIVALS", "rivals_our15_exposure"),
            ("COMPETITIVE", "competitive_our15_exposure"),
        ):
            scope = dict(scopes.get(scope_key) or {})
            rows = [
                dict(row)
                for row in s15b.get(payload_key) or []
                if isinstance(row, Mapping)
            ]
            if len(rows) != 15:
                failures.append(
                    f"S15B_OUR15_SCOPE_COUNT={scope_key}:{len(rows)}/15"
                )
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

        competitive = dict(s15b.get("competitive_window") or {})
        expected_window = resolve_competitive_window(
            competitive.get("our_rank"),
            competitive.get("league_size"),
        )
        for key in (
            "window_mode", "above_count", "below_count", "rival_count", "ranks"
        ):
            if competitive.get(key) != expected_window.get(key):
                failures.append(f"S15B_COMPETITIVE_WINDOW_INVALID={key}")
        try:
            window_expected = int(competitive.get("rival_count"))
            standings_count = int(competitive.get("standings_rival_count"))
            picks_count = int(competitive.get("picks_available_count"))
            scope_expected = int(competitive_scope.get("expected"))
            scope_collected = int(competitive_scope.get("collected"))
            scope_denominator = int(competitive_scope.get("denominator"))
        except (TypeError, ValueError):
            window_expected = standings_count = picks_count = -1
            scope_expected = scope_collected = scope_denominator = -1
        if (
            window_expected < 0
            or standings_count != window_expected
            or scope_expected != window_expected
            or scope_collected != picks_count
            or scope_denominator != picks_count
        ):
            failures.append("S15B_COMPETITIVE_SCOPE_COHORT_RELATION_INVALID")

        expected_ranks = set(expected_window.get("ranks") or [])
        competitive_rivals = [
            dict(row)
            for row in s15b.get("competitive_rivals") or []
            if isinstance(row, Mapping)
        ]
        for index, rival in enumerate(competitive_rivals, start=1):
            rank = int(rival.get("rank") or 0)
            if rank not in expected_ranks:
                failures.append(
                    f"S15B_COMPETITIVE_RIVAL_OUTSIDE_WINDOW={index}:{rank}"
                )
            expected_position = (
                "ABOVE"
                if rank < int(expected_window.get("our_rank") or 0)
                else "BELOW"
            )
            if rival.get("position_vs_us") != expected_position:
                failures.append(
                    f"S15B_COMPETITIVE_POSITION_INVALID={index}"
                )
            for key in (
                "xi_overlap_count",
                "shields",
                "rival_only_threats",
                "differential_against_us",
            ):
                if key not in rival:
                    failures.append(
                        f"S15B_COMPETITIVE_RIVAL_DETAIL_MISSING={index}:{key}"
                    )

        top10 = [
            int(row.get("rank") or 0)
            for row in s15b.get("rank_battle") or []
            if isinstance(row, Mapping)
        ]
        expected_top10 = list(range(1, min(10, league_expected) + 1))
        if top10 != expected_top10:
            failures.append("S15B_TOP10_MILESTONE_INVALID")

        for index, row in enumerate(
            s15b.get("competitive_window_threats") or [],
            start=1,
        ):
            if not isinstance(row, Mapping):
                continue
            if row.get("denominator") != competitive_scope.get("denominator"):
                failures.append(
                    f"S15B_COMPETITIVE_THREAT_DENOMINATOR_MISMATCH={index}"
                )
                break

        for index, row in enumerate(s15b.get("captain_leverage") or [], start=1):
            if not isinstance(row, Mapping):
                continue
            if not isinstance(row.get("competitive_scope"), Mapping):
                failures.append(
                    f"S15B_CAPTAIN_COMPETITIVE_SCOPE_MISSING={index}"
                )
                break

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
            "COMPETITIVE WINDOW",
            "POSITION VS US",
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
