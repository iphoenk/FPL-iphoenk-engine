from __future__ import annotations

"""R4 section-level report-compute contract.

Validates deterministic content shape for mandatory FPL Master report sections
before rendering. Source truthfulness belongs to R5 and visible-body parsing to R6.
"""

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from .delivery_integrity import validate_rank20, validate_watchlist20


SECTION_CONTRACT_REGISTRY: dict[str, Mapping[str, Any]] = {
    "OUR15": {
        "exact_count": 15,
        "positions": {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
    },
    "XI_BENCH": {"xi_count": 11, "bench_count": 4, "bench_gk": 1},
    "WATCHLIST20": {
        "exact_count": 20,
        "positions": {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5},
    },
    "RISE20": {"exact_count": 20, "validator": "validate_rank20"},
    "FALL20": {"exact_count": 20, "validator": "validate_rank20"},
    "WEATHER": {
        "content_states": ("PASS", "DEGRADED"),
        "row_fields": (
            "fixture",
            "venue_kickoff",
            "forecast_time",
            "temperature",
            "precipitation",
            "wind_gust",
            "severity",
            "fpl_impact",
        ),
    },
    "ICON14B": {
        "content_states": ("PASS", "PARTIAL"),
        "fields": (
            "current_rank",
            "total_points",
            "gap_to_first",
            "nearest_above",
            "nearest_below",
            "ownership_share",
            "starter_share",
            "captain_exposure",
            "vice_captain_exposure",
            "chip_exposure",
            "eo",
            "shared_core",
            "shields",
            "positive_differentials",
            "dangers",
            "direct_rival_equation",
            "rank_leverage",
            "remaining_ammunition",
            "rival_divergences",
            "support_oppose_by_match",
            "scenario_paths",
            "strategic_implication",
        ),
    },
    "ALL15_TACTICAL": {
        "exact_count": 15,
        "row_fields": (
            "element_id",
            "opponent_h_a",
            "next_gw_fdr",
            "own_team_shape",
            "opponent_shape",
            "role_archetype",
            "direct_opponent_zone_channel",
            "player_style_fit",
            "coach_system_interaction",
            "set_piece_penalty_relevance",
            "rest_weather",
            "p_start",
            "xmins",
            "gw_plus_1_xpts",
            "matchup_grade",
            "decision_implication",
        ),
    },
    "OPTIMIZER": {
        "content_states": ("PASS", "PARTIAL"),
        "route_fields": (
            "route_id",
            "category",
            "outs",
            "ins",
            "transfer_count",
            "hit",
            "resulting_itb",
            "legality",
            "resulting_formation",
            "xi_changes",
            "bench_changes",
            "gross_projected_gain",
            "net_projected_gain",
            "xpts3_delta",
            "xpts5_delta",
            "uncertainty",
            "price_impact",
            "optionality_impact",
            "break_even_gw",
        ),
    },
    "TRANSFER_STAGE": {
        "fields": ("stage", "route", "trigger", "information_value", "reversal_conditions"),
        "stages": ("WAIT", "PREPARE", "ACT"),
    },
    "PRICE_RISK": {
        "fields": (
            "owned_rows",
            "candidate_rows",
            "package_affordability",
            "price_optionality",
            "source_freshness",
        ),
        "row_fields": (
            "element_id",
            "current_price",
            "direction",
            "urgency",
            "affordability_impact",
            "decision_impact",
        ),
    },
}

_REQUIRED_SECTIONS = tuple(SECTION_CONTRACT_REGISTRY)
_POSITION_ALIASES = {"GKP": "GK", "GOALKEEPER": "GK"}


def player_id(row: Any) -> int | str | None:
    if not isinstance(row, Mapping):
        return None
    for key in ("element_id", "player_id", "id"):
        if row.get(key) is not None:
            return row[key]
    return None


def player_position(row: Any) -> str:
    if not isinstance(row, Mapping):
        return ""
    raw = str(row.get("position") or row.get("pos") or "").strip().upper()
    return _POSITION_ALIASES.get(raw, raw)


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _missing_keys(row: Mapping[str, Any], fields: Iterable[str]) -> list[str]:
    return [field for field in fields if field not in row]


def _validate_row_schema(
    rows: Sequence[Any],
    *,
    fields: Sequence[str],
    nonempty_fields: Iterable[str] = (),
) -> list[str]:
    failures: list[str] = []
    required_nonempty = set(nonempty_fields)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            failures.append(f"ROW_INVALID={index}")
            continue
        missing = _missing_keys(row, fields)
        if missing:
            failures.append(f"ROW_SCHEMA_MISSING={index}:{','.join(missing)}")
        for field in required_nonempty:
            if field in row and not _nonempty(row.get(field)):
                failures.append(f"ROW_FIELD_EMPTY={index}:{field}")
    return failures


def _result(*, failures: Sequence[str], **details: Any) -> dict[str, Any]:
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": list(failures),
        **details,
    }


def validate_our15_section(rows: Sequence[Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["OUR15"]
    ids = [player_id(row) for row in rows]
    concrete_ids = [value for value in ids if value is not None]
    positions = Counter(player_position(row) for row in rows)
    failures: list[str] = []
    if len(rows) != contract["exact_count"]:
        failures.append(f"TOTAL={len(rows)}")
    if any(value is None for value in ids):
        failures.append("IDENTITY_MISSING")
    if len(set(concrete_ids)) != len(concrete_ids):
        failures.append("IDENTITY_DUPLICATE")
    for position, target in contract["positions"].items():
        if positions.get(position, 0) != target:
            failures.append(f"{position}={positions.get(position, 0)}")
    return _result(
        failures=failures,
        total=len(rows),
        ids=concrete_ids,
        positions={key: positions.get(key, 0) for key in contract["positions"]},
    )


def validate_xi_bench_section(
    payload: Mapping[str, Any],
    *,
    our15_rows: Sequence[Any],
) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["XI_BENCH"]
    missing = _missing_keys(payload, ("starting_xi_ids", "bench_ids"))
    failures = [f"MISSING_FIELD={field}" for field in missing]
    xi = list(payload.get("starting_xi_ids") or [])
    bench = list(payload.get("bench_ids") or [])
    our15_by_id = {
        identity: row
        for row in our15_rows
        if isinstance(row, Mapping) and (identity := player_id(row)) is not None
    }
    owned_ids = set(our15_by_id)

    xi_failures: list[str] = []
    if len(xi) != contract["xi_count"]:
        xi_failures.append(f"TOTAL={len(xi)}")
    if len(set(xi)) != len(xi):
        xi_failures.append("IDENTITY_DUPLICATE")
    outside_xi = set(xi) - owned_ids
    if outside_xi:
        xi_failures.append(f"NOT_OWNED={len(outside_xi)}")
    xi_positions = Counter(
        player_position(our15_by_id[identity])
        for identity in xi
        if identity in our15_by_id
    )
    if xi_positions.get("GK", 0) != 1:
        xi_failures.append(f"GK={xi_positions.get('GK', 0)}")
    if not 3 <= xi_positions.get("DEF", 0) <= 5:
        xi_failures.append(f"DEF={xi_positions.get('DEF', 0)}")
    if not 2 <= xi_positions.get("MID", 0) <= 5:
        xi_failures.append(f"MID={xi_positions.get('MID', 0)}")
    if not 1 <= xi_positions.get("FWD", 0) <= 3:
        xi_failures.append(f"FWD={xi_positions.get('FWD', 0)}")

    bench_failures: list[str] = []
    if len(bench) != contract["bench_count"]:
        bench_failures.append(f"TOTAL={len(bench)}")
    if len(set(bench)) != len(bench):
        bench_failures.append("IDENTITY_DUPLICATE")
    outside_bench = set(bench) - owned_ids
    if outside_bench:
        bench_failures.append(f"NOT_OWNED={len(outside_bench)}")
    if set(bench) != owned_ids - set(xi):
        bench_failures.append("NOT_EXACT_OUR15_COMPLEMENT")
    bench_gk = sum(
        1
        for identity in bench
        if identity in our15_by_id and player_position(our15_by_id[identity]) == "GK"
    )
    if bench_gk != contract["bench_gk"]:
        bench_failures.append(f"GK={bench_gk}")

    if xi_failures:
        failures.append("XI_INVALID")
    if bench_failures:
        failures.append("BENCH_INVALID")
    return _result(
        failures=failures,
        XI=_result(
            failures=xi_failures,
            total=len(xi),
            ids=xi,
            positions={key: xi_positions.get(key, 0) for key in ("GK", "DEF", "MID", "FWD")},
        ),
        BENCH=_result(failures=bench_failures, total=len(bench), ids=bench, goalkeepers=bench_gk),
    )


def validate_weather_section(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["WEATHER"]
    state = str(payload.get("content_state") or "").strip().upper()
    failures: list[str] = []
    if state not in contract["content_states"]:
        failures.append(f"CONTENT_STATE_INVALID={state or '<empty>'}")
    rows = payload.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        failures.append("ROWS_INVALID")
        rows = []
    if state == "DEGRADED":
        if str(payload.get("source_status") or "").strip().upper() != "DEGRADED":
            failures.append("SOURCE_STATUS_NOT_DEGRADED")
        if not _nonempty(payload.get("degradation_reason")):
            failures.append("DEGRADATION_REASON_MISSING")
    elif state == "PASS" and not rows:
        failures.append("ROWS_EMPTY")
    failures.extend(
        _validate_row_schema(
            rows,
            fields=contract["row_fields"],
            nonempty_fields=contract["row_fields"],
        )
    )
    return _result(failures=failures, content_state=state, row_count=len(rows))


def validate_icon14b_section(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["ICON14B"]
    state = str(payload.get("content_state") or "").strip().upper()
    failures: list[str] = []
    if state not in contract["content_states"]:
        failures.append(f"CONTENT_STATE_INVALID={state or '<empty>'}")
    missing = _missing_keys(payload, contract["fields"])
    failures.extend(f"MISSING_FIELD={field}" for field in missing)
    for field in contract["fields"]:
        if field in payload and not _nonempty(payload.get(field)):
            failures.append(f"FIELD_EMPTY={field}")
    if state == "PARTIAL":
        missing_fields = payload.get("missing_fields")
        if not isinstance(missing_fields, Sequence) or isinstance(missing_fields, (str, bytes)) or not missing_fields:
            failures.append("MISSING_FIELDS_METADATA_REQUIRED")
        if not _nonempty(payload.get("degradation_reason")):
            failures.append("DEGRADATION_REASON_MISSING")
    return _result(failures=failures, content_state=state)


def validate_all15_tactical_section(
    rows: Sequence[Any],
    *,
    owned_ids: Iterable[int | str],
) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["ALL15_TACTICAL"]
    owned = set(owned_ids)
    ids = [player_id(row) for row in rows]
    concrete_ids = [value for value in ids if value is not None]
    failures: list[str] = []
    if len(rows) != contract["exact_count"]:
        failures.append(f"TOTAL={len(rows)}")
    if any(value is None for value in ids):
        failures.append("IDENTITY_MISSING")
    if len(set(concrete_ids)) != len(concrete_ids):
        failures.append("IDENTITY_DUPLICATE")
    if set(concrete_ids) != owned:
        failures.append("OWNED_ID_SET_MISMATCH")
    failures.extend(
        _validate_row_schema(
            rows,
            fields=contract["row_fields"],
            nonempty_fields=contract["row_fields"],
        )
    )
    return _result(failures=failures, total=len(rows), ids=concrete_ids)


def validate_optimizer_section(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["OPTIMIZER"]
    state = str(payload.get("content_state") or "").strip().upper()
    failures: list[str] = []
    if state not in contract["content_states"]:
        failures.append(f"CONTENT_STATE_INVALID={state or '<empty>'}")
    routes = payload.get("routes")
    if not isinstance(routes, Sequence) or isinstance(routes, (str, bytes)):
        failures.append("ROUTES_INVALID")
        routes = []
    if state == "PARTIAL":
        if not _nonempty(payload.get("degradation_reason")):
            failures.append("DEGRADATION_REASON_MISSING")
    elif state == "PASS" and not routes:
        failures.append("ROUTES_EMPTY")
    failures.extend(
        _validate_row_schema(
            routes,
            fields=contract["route_fields"],
            nonempty_fields=contract["route_fields"],
        )
    )
    for index, route in enumerate(routes, start=1):
        if not isinstance(route, Mapping):
            continue
        transfer_count = route.get("transfer_count")
        if not isinstance(transfer_count, int) or isinstance(transfer_count, bool) or transfer_count < 0:
            failures.append(f"ROW_TRANSFER_COUNT_INVALID={index}")
            continue
        outs = route.get("outs")
        ins = route.get("ins")
        if not isinstance(outs, Sequence) or isinstance(outs, (str, bytes)):
            failures.append(f"ROW_OUTS_INVALID={index}")
        if not isinstance(ins, Sequence) or isinstance(ins, (str, bytes)):
            failures.append(f"ROW_INS_INVALID={index}")
        if isinstance(outs, Sequence) and not isinstance(outs, (str, bytes)) and len(outs) != transfer_count:
            failures.append(f"ROW_OUT_COUNT_MISMATCH={index}")
        if isinstance(ins, Sequence) and not isinstance(ins, (str, bytes)) and len(ins) != transfer_count:
            failures.append(f"ROW_IN_COUNT_MISMATCH={index}")
        if str(route.get("legality") or "").strip().upper() != "PASS":
            failures.append(f"ROW_LEGALITY_NOT_PASS={index}")
    return _result(failures=failures, content_state=state, route_count=len(routes))


def validate_transfer_stage_section(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["TRANSFER_STAGE"]
    missing = _missing_keys(payload, contract["fields"])
    failures = [f"MISSING_FIELD={field}" for field in missing]
    stage = str(payload.get("stage") or "").strip().upper()
    if stage not in contract["stages"]:
        failures.append(f"STAGE_INVALID={stage or '<empty>'}")
    for field in ("route", "trigger", "information_value"):
        if field in payload and not _nonempty(payload.get(field)):
            failures.append(f"FIELD_EMPTY={field}")
    reversals = payload.get("reversal_conditions")
    if "reversal_conditions" in payload:
        if not isinstance(reversals, Sequence) or isinstance(reversals, (str, bytes)) or not reversals:
            failures.append("REVERSAL_CONDITIONS_INVALID")
    return _result(failures=failures, stage=stage)


def validate_price_risk_section(
    payload: Mapping[str, Any],
    *,
    owned_ids: Iterable[int | str],
) -> dict[str, Any]:
    contract = SECTION_CONTRACT_REGISTRY["PRICE_RISK"]
    missing = _missing_keys(payload, contract["fields"])
    failures = [f"MISSING_FIELD={field}" for field in missing]
    owned_rows = payload.get("owned_rows")
    candidate_rows = payload.get("candidate_rows")
    if not isinstance(owned_rows, Sequence) or isinstance(owned_rows, (str, bytes)):
        failures.append("OWNED_ROWS_INVALID")
        owned_rows = []
    if not isinstance(candidate_rows, Sequence) or isinstance(candidate_rows, (str, bytes)):
        failures.append("CANDIDATE_ROWS_INVALID")
        candidate_rows = []
    failures.extend(
        _validate_row_schema(
            owned_rows,
            fields=contract["row_fields"],
            nonempty_fields=contract["row_fields"],
        )
    )
    failures.extend(
        f"CANDIDATE_{failure}"
        for failure in _validate_row_schema(
            candidate_rows,
            fields=contract["row_fields"],
            nonempty_fields=contract["row_fields"],
        )
    )
    owned_row_ids = [player_id(row) for row in owned_rows]
    concrete_owned = [value for value in owned_row_ids if value is not None]
    if any(value is None for value in owned_row_ids):
        failures.append("OWNED_ID_MISSING")
    if len(set(concrete_owned)) != len(concrete_owned):
        failures.append("OWNED_ID_DUPLICATE")
    if set(concrete_owned) != set(owned_ids):
        failures.append("OWNED_ID_SET_MISMATCH")
    candidate_ids = [player_id(row) for row in candidate_rows]
    concrete_candidates = [value for value in candidate_ids if value is not None]
    if any(value is None for value in candidate_ids):
        failures.append("CANDIDATE_ID_MISSING")
    if len(set(concrete_candidates)) != len(concrete_candidates):
        failures.append("CANDIDATE_ID_DUPLICATE")
    for field in ("package_affordability", "price_optionality", "source_freshness"):
        if field in payload and not _nonempty(payload.get(field)):
            failures.append(f"FIELD_EMPTY={field}")
    return _result(
        failures=failures,
        owned_count=len(owned_rows),
        candidate_count=len(candidate_rows),
        owned_ids=concrete_owned,
    )


def validate_report_sections(
    payload: Mapping[str, Any],
    *,
    universe_ids: Iterable[int | str] | None = None,
) -> dict[str, Any]:
    """Validate every R4 section payload through one fail-closed registry."""
    missing_sections = [section for section in _REQUIRED_SECTIONS if section not in payload]
    checks: dict[str, dict[str, Any]] = {}

    our15_rows = payload.get("OUR15") if isinstance(payload.get("OUR15"), Sequence) else []
    if isinstance(our15_rows, (str, bytes)):
        our15_rows = []
    checks["OUR15"] = validate_our15_section(our15_rows)
    owned_ids = checks["OUR15"]["ids"]

    xi_bench = payload.get("XI_BENCH") if isinstance(payload.get("XI_BENCH"), Mapping) else {}
    checks["XI_BENCH"] = validate_xi_bench_section(xi_bench, our15_rows=our15_rows)

    watchlist_rows = payload.get("WATCHLIST20") if isinstance(payload.get("WATCHLIST20"), Sequence) else []
    if isinstance(watchlist_rows, (str, bytes)):
        watchlist_rows = []
    checks["WATCHLIST20"] = validate_watchlist20(
        watchlist_rows,
        owned_ids=owned_ids,
        universe_ids=universe_ids,
    )

    rise_rows = payload.get("RISE20") if isinstance(payload.get("RISE20"), Sequence) else []
    fall_rows = payload.get("FALL20") if isinstance(payload.get("FALL20"), Sequence) else []
    if isinstance(rise_rows, (str, bytes)):
        rise_rows = []
    if isinstance(fall_rows, (str, bytes)):
        fall_rows = []
    checks["RISE20"] = validate_rank20(rise_rows, label="RISE20")
    checks["FALL20"] = validate_rank20(fall_rows, label="FALL20")

    weather = payload.get("WEATHER") if isinstance(payload.get("WEATHER"), Mapping) else {}
    icon14b = payload.get("ICON14B") if isinstance(payload.get("ICON14B"), Mapping) else {}
    tactical = payload.get("ALL15_TACTICAL") if isinstance(payload.get("ALL15_TACTICAL"), Sequence) else []
    if isinstance(tactical, (str, bytes)):
        tactical = []
    optimizer = payload.get("OPTIMIZER") if isinstance(payload.get("OPTIMIZER"), Mapping) else {}
    transfer_stage = payload.get("TRANSFER_STAGE") if isinstance(payload.get("TRANSFER_STAGE"), Mapping) else {}
    price_risk = payload.get("PRICE_RISK") if isinstance(payload.get("PRICE_RISK"), Mapping) else {}

    checks["WEATHER"] = validate_weather_section(weather)
    checks["ICON14B"] = validate_icon14b_section(icon14b)
    checks["ALL15_TACTICAL"] = validate_all15_tactical_section(tactical, owned_ids=owned_ids)
    checks["OPTIMIZER"] = validate_optimizer_section(optimizer)
    checks["TRANSFER_STAGE"] = validate_transfer_stage_section(transfer_stage)
    checks["PRICE_RISK"] = validate_price_risk_section(price_risk, owned_ids=owned_ids)

    failures = list(missing_sections)
    failures.extend(
        section
        for section in _REQUIRED_SECTIONS
        if section not in missing_sections and checks[section]["status"] != "PASS"
    )
    return {
        "status": "PASS" if not failures else "FAIL",
        "section_contract_ready": not failures,
        "failures": failures,
        "missing_sections": missing_sections,
        "checks": checks,
        "registry_sections": list(_REQUIRED_SECTIONS),
    }
