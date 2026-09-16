from __future__ import annotations

"""Deterministic downstream report-compute integrity contract.

This module validates the shape and partitioning of already-resolved report inputs.
It does not acquire data, publish V6 artifacts, or implement FPL prediction models.
"""

from collections import Counter
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .delivery_integrity import RANK20_REQUIRED_FIELDS, validate_rank20, validate_watchlist20
from .rank20_engine import build_rank20_tables


_SQUAD_POSITION_TARGET = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
_POSITION_ALIASES = {"GKP": "GK", "GOALKEEPER": "GK"}


def _player_id(row: Mapping[str, Any]) -> int | str | None:
    for key in ("element_id", "player_id", "id"):
        if row.get(key) is not None:
            return row[key]
    return None


def _position(row: Mapping[str, Any]) -> str:
    raw = str(row.get("position") or row.get("pos") or "").upper()
    return _POSITION_ALIASES.get(raw, raw)


def _sort_ids(values: Sequence[int | str]) -> list[int | str]:
    return sorted(values, key=lambda value: (type(value).__name__, str(value)))


def _validate_our15(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [_player_id(row) for row in rows]
    positions = Counter(_position(row) for row in rows)
    failures: list[str] = []

    if len(rows) != 15:
        failures.append(f"TOTAL={len(rows)}")
    if any(player_id is None for player_id in ids):
        failures.append("IDENTITY_MISSING")
    concrete_ids = [player_id for player_id in ids if player_id is not None]
    if len(set(concrete_ids)) != len(concrete_ids):
        failures.append("IDENTITY_DUPLICATE")
    for position, target in _SQUAD_POSITION_TARGET.items():
        if positions.get(position, 0) != target:
            failures.append(f"{position}={positions.get(position, 0)}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "total": len(rows),
        "positions": {
            position: positions.get(position, 0)
            for position in _SQUAD_POSITION_TARGET
        },
        "ids": concrete_ids,
    }


def _validate_starting_xi(
    starting_xi_ids: Sequence[int | str],
    *,
    our15_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    failures: list[str] = []
    xi = list(starting_xi_ids)
    our15_by_id = {
        player_id: row
        for row in our15_rows
        if (player_id := _player_id(row)) is not None
    }

    if len(xi) != 11:
        failures.append(f"TOTAL={len(xi)}")
    if len(set(xi)) != len(xi):
        failures.append("IDENTITY_DUPLICATE")

    outside = sorted(set(xi) - set(our15_by_id), key=str)
    if outside:
        failures.append(f"NOT_OWNED={len(outside)}")

    positions = Counter(
        _position(our15_by_id[player_id])
        for player_id in xi
        if player_id in our15_by_id
    )
    if positions.get("GK", 0) != 1:
        failures.append(f"GK={positions.get('GK', 0)}")
    if not 3 <= positions.get("DEF", 0) <= 5:
        failures.append(f"DEF={positions.get('DEF', 0)}")
    if not 2 <= positions.get("MID", 0) <= 5:
        failures.append(f"MID={positions.get('MID', 0)}")
    if not 1 <= positions.get("FWD", 0) <= 3:
        failures.append(f"FWD={positions.get('FWD', 0)}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "total": len(xi),
        "positions": {
            position: positions.get(position, 0)
            for position in _SQUAD_POSITION_TARGET
        },
        "ids": xi,
    }


def _validate_bench(
    bench_ids: Sequence[int | str],
    *,
    starting_xi_ids: Sequence[int | str],
    our15_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    failures: list[str] = []
    bench = list(bench_ids)
    our15_by_id = {
        player_id: row
        for row in our15_rows
        if (player_id := _player_id(row)) is not None
    }
    our15_ids = set(our15_by_id)
    xi_ids = set(starting_xi_ids)

    if len(bench) != 4:
        failures.append(f"TOTAL={len(bench)}")
    if len(set(bench)) != len(bench):
        failures.append("IDENTITY_DUPLICATE")
    if set(bench) != our15_ids - xi_ids:
        failures.append("NOT_EXACT_OUR15_COMPLEMENT")
    outside = sorted(set(bench) - our15_ids, key=str)
    if outside:
        failures.append(f"NOT_OWNED={len(outside)}")

    bench_gk = sum(
        1
        for player_id in bench
        if player_id in our15_by_id and _position(our15_by_id[player_id]) == "GK"
    )
    if bench_gk != 1:
        failures.append(f"GK={bench_gk}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "total": len(bench),
        "goalkeepers": bench_gk,
        "ids": bench,
    }


def _validate_fact_model_partition(
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
) -> dict[str, Any]:
    fact_keys = {str(key) for key in facts}
    model_keys = {str(key) for key in models}
    overlap = sorted(fact_keys & model_keys)
    failures: list[str] = []

    if overlap:
        failures.append(f"FACT_MODEL_OVERLAP={','.join(overlap)}")

    for key, value in facts.items():
        if not isinstance(value, Mapping) or not str(value.get("source") or "").strip():
            failures.append(f"FACT_SOURCE_MISSING={key}")
    for key, value in models.items():
        if not isinstance(value, Mapping) or not str(value.get("model") or "").strip():
            failures.append(f"MODEL_ID_MISSING={key}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "fact_keys": sorted(fact_keys),
        "model_keys": sorted(model_keys),
        "overlap": overlap,
    }


def _rank20_fingerprint_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bind the compute fingerprint to the R2 row contract, not identities alone."""
    return [
        {field: row.get(field) for field in RANK20_REQUIRED_FIELDS}
        for row in rows
    ]


def _compute_fingerprint(
    *,
    our15_rows: Sequence[Mapping[str, Any]],
    starting_xi_ids: Sequence[int | str],
    bench_ids: Sequence[int | str],
    watchlist_rows: Sequence[Mapping[str, Any]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
) -> str:
    our15 = sorted(
        (
            {"id": _player_id(row), "position": _position(row)}
            for row in our15_rows
        ),
        key=lambda row: (str(row["id"]), row["position"]),
    )
    payload = {
        "OUR15": our15,
        "XI": _sort_ids(list(starting_xi_ids)),
        "BENCH": _sort_ids(list(bench_ids)),
        "WATCHLIST20": [_player_id(row) for row in watchlist_rows],
        "RISE20": _rank20_fingerprint_rows(rise_rows),
        "FALL20": _rank20_fingerprint_rows(fall_rows),
        "FACT": dict(facts),
        "MODEL": dict(models),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def build_report_compute_contract(
    *,
    scope_matrix_report_ready: bool,
    our15_rows: Sequence[Mapping[str, Any]],
    starting_xi_ids: Sequence[int | str],
    bench_ids: Sequence[int | str],
    watchlist_rows: Sequence[Mapping[str, Any]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
) -> dict[str, Any]:
    """Validation primitive for an already-materialized report-compute payload."""
    if not scope_matrix_report_ready:
        return {
            "status": "BLOCKED",
            "compute_ready": False,
            "delivery_ready": False,
            "next_action": "RESOLVE_REPORT_SCOPES",
            "failures": ["SCOPE_MATRIX_NOT_READY"],
            "legacy_fallback_allowed": False,
            "compute_fingerprint": None,
        }

    our15 = _validate_our15(our15_rows)
    xi = _validate_starting_xi(starting_xi_ids, our15_rows=our15_rows)
    bench = _validate_bench(
        bench_ids,
        starting_xi_ids=starting_xi_ids,
        our15_rows=our15_rows,
    )
    watchlist = validate_watchlist20(
        watchlist_rows,
        owned_ids=our15["ids"],
    )
    rise = validate_rank20(rise_rows, label="RISE20")
    fall = validate_rank20(fall_rows, label="FALL20")
    fact_model = _validate_fact_model_partition(facts, models)

    checks = {
        "OUR15": our15,
        "XI": xi,
        "BENCH": bench,
        "WATCHLIST20": watchlist,
        "RISE20": rise,
        "FALL20": fall,
        "FACT_MODEL": fact_model,
    }
    failures = [name for name, result in checks.items() if result["status"] != "PASS"]
    compute_ready = not failures

    return {
        "status": "PASS" if compute_ready else "FAIL",
        "compute_ready": compute_ready,
        "delivery_ready": False,
        "next_action": "PRE_RENDER_QA" if compute_ready else "RECOMPUTE",
        "failures": failures,
        "legacy_fallback_allowed": False,
        "compute_fingerprint": _compute_fingerprint(
            our15_rows=our15_rows,
            starting_xi_ids=starting_xi_ids,
            bench_ids=bench_ids,
            watchlist_rows=watchlist_rows,
            rise_rows=rise_rows,
            fall_rows=fall_rows,
            facts=facts,
            models=models,
        ),
        **checks,
    }


def build_report_compute_contract_from_universe(
    *,
    scope_matrix_report_ready: bool,
    our15_rows: Sequence[Mapping[str, Any]],
    starting_xi_ids: Sequence[int | str],
    bench_ids: Sequence[int | str],
    watchlist_rows: Sequence[Mapping[str, Any]],
    universe_rows: Sequence[Mapping[str, Any]],
    predictor_rows: Sequence[Mapping[str, Any]],
    rank_snapshot: Mapping[str, Any],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonical R3 entrypoint: build RISE/FALL from the full universe, then validate.

    The older ``build_report_compute_contract`` remains a low-level validation
    primitive for tests and already-materialized compatibility callers. New report
    construction should enter here so canonical RISE20/FALL20 cannot bypass R3
    selection, tie-breaking, ETA, ownership-tag and snapshot-provenance rules.
    """
    if not scope_matrix_report_ready:
        blocked = build_report_compute_contract(
            scope_matrix_report_ready=False,
            our15_rows=our15_rows,
            starting_xi_ids=starting_xi_ids,
            bench_ids=bench_ids,
            watchlist_rows=watchlist_rows,
            rise_rows=(),
            fall_rows=(),
            facts=facts,
            models=models,
        )
        return {
            **blocked,
            "RANK20_ENGINE": {
                "status": "BLOCKED",
                "reason": "SCOPE_MATRIX_NOT_READY",
                "full_universe_coverage": False,
            },
            "RISE20_ROWS": [],
            "FALL20_ROWS": [],
        }

    owned_ids = [
        player_id
        for row in our15_rows
        if (player_id := _player_id(row)) is not None
    ]
    rank20 = build_rank20_tables(
        universe_rows=universe_rows,
        predictor_rows=predictor_rows,
        owned_ids=owned_ids,
        snapshot=rank_snapshot,
    )
    result = build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15_rows,
        starting_xi_ids=starting_xi_ids,
        bench_ids=bench_ids,
        watchlist_rows=watchlist_rows,
        rise_rows=rank20["RISE20"],
        fall_rows=rank20["FALL20"],
        facts=facts,
        models=models,
    )
    engine_metadata = {
        key: value
        for key, value in rank20.items()
        if key not in {"RISE20", "FALL20"}
    }
    return {
        **result,
        "RANK20_ENGINE": {"status": "PASS", **engine_metadata},
        "RISE20_ROWS": rank20["RISE20"],
        "FALL20_ROWS": rank20["FALL20"],
    }
