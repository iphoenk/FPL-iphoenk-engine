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

    return list(dict.fromkeys(failures))
