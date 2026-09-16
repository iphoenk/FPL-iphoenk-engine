from __future__ import annotations

"""Deterministic downstream report-compute integrity contract.

This module validates already-resolved report inputs. R4 owns structural section
completeness and R5 owns provenance/anti-fabrication. It does not acquire data,
publish V6 artifacts, parse the final rendered body, or implement prediction models.
"""

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .delivery_integrity import RANK20_REQUIRED_FIELDS
from .provenance_guard import validate_report_provenance
from .rank20_engine import build_rank20_tables
from .section_contract import player_id, player_position, validate_report_sections


_R4_EXTRA_SECTIONS = (
    "WEATHER",
    "ICON14B",
    "ALL15_TACTICAL",
    "OPTIMIZER",
    "TRANSFER_STAGE",
    "PRICE_RISK",
)


def _sort_ids(values: Sequence[int | str]) -> list[int | str]:
    return sorted(values, key=lambda value: (type(value).__name__, str(value)))


def _rank20_fingerprint_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bind the compute fingerprint to the R2 row contract, not identities alone."""
    return [
        {field: row.get(field) for field in RANK20_REQUIRED_FIELDS}
        for row in rows
    ]


def _compose_section_payloads(
    *,
    our15_rows: Sequence[Mapping[str, Any]],
    starting_xi_ids: Sequence[int | str],
    bench_ids: Sequence[int | str],
    watchlist_rows: Sequence[Mapping[str, Any]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    section_payloads: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one R4 validation payload without allowing callers to override core sections."""
    result = {
        section: section_payloads[section]
        for section in _R4_EXTRA_SECTIONS
        if section in section_payloads
    }
    result.update(
        {
            "OUR15": list(our15_rows),
            "XI_BENCH": {
                "starting_xi_ids": list(starting_xi_ids),
                "bench_ids": list(bench_ids),
            },
            "WATCHLIST20": list(watchlist_rows),
            "RISE20": list(rise_rows),
            "FALL20": list(fall_rows),
        }
    )
    return result


def _compute_fingerprint(
    *,
    our15_rows: Sequence[Mapping[str, Any]],
    starting_xi_ids: Sequence[int | str],
    bench_ids: Sequence[int | str],
    watchlist_rows: Sequence[Mapping[str, Any]],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    section_payloads: Mapping[str, Any],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
    inferences: Mapping[str, Any],
) -> str:
    our15 = sorted(
        (
            {"id": player_id(row), "position": player_position(row)}
            for row in our15_rows
        ),
        key=lambda row: (str(row["id"]), row["position"]),
    )
    r4_extras = {
        section: section_payloads.get(section)
        for section in _R4_EXTRA_SECTIONS
    }
    payload = {
        "OUR15": our15,
        "XI": _sort_ids(list(starting_xi_ids)),
        "BENCH": _sort_ids(list(bench_ids)),
        "WATCHLIST20": [player_id(row) for row in watchlist_rows],
        "RISE20": _rank20_fingerprint_rows(rise_rows),
        "FALL20": _rank20_fingerprint_rows(fall_rows),
        "R4_EXTRA_SECTIONS": r4_extras,
        "FACT": dict(facts),
        "MODEL": dict(models),
        "INFERENCE": dict(inferences),
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
    section_payloads: Mapping[str, Any],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
    inferences: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate materialized report-compute input through R4 and R5.

    ``section_payloads`` and ``inferences`` are mandatory. Compatibility callers
    cannot bypass section completeness or provenance by omitting the new contracts.
    """
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

    full_section_payload = _compose_section_payloads(
        our15_rows=our15_rows,
        starting_xi_ids=starting_xi_ids,
        bench_ids=bench_ids,
        watchlist_rows=watchlist_rows,
        rise_rows=rise_rows,
        fall_rows=fall_rows,
        section_payloads=section_payloads,
    )
    section_contract = validate_report_sections(full_section_payload)
    provenance = validate_report_provenance(
        section_payloads=section_payloads,
        facts=facts,
        models=models,
        inferences=inferences,
    )

    section_checks = section_contract["checks"]
    xi_bench = section_checks["XI_BENCH"]
    compatibility_checks = {
        "OUR15": section_checks["OUR15"],
        "XI": xi_bench["XI"],
        "BENCH": xi_bench["BENCH"],
        "WATCHLIST20": section_checks["WATCHLIST20"],
        "RISE20": section_checks["RISE20"],
        "FALL20": section_checks["FALL20"],
        "FACT_MODEL": provenance["partition"],
        "SECTION_CONTRACT": section_contract,
        "PROVENANCE": provenance,
    }
    failures: list[str] = []
    if section_contract["status"] != "PASS":
        failures.append("SECTION_CONTRACT")
    if provenance["status"] != "PASS":
        failures.append("PROVENANCE")
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
            section_payloads=section_payloads,
            facts=facts,
            models=models,
            inferences=inferences,
        ),
        **compatibility_checks,
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
    section_payloads: Mapping[str, Any],
    facts: Mapping[str, Any],
    models: Mapping[str, Any],
    inferences: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonical R3+R4+R5 entrypoint for full report construction."""
    if not scope_matrix_report_ready:
        blocked = build_report_compute_contract(
            scope_matrix_report_ready=False,
            our15_rows=our15_rows,
            starting_xi_ids=starting_xi_ids,
            bench_ids=bench_ids,
            watchlist_rows=watchlist_rows,
            rise_rows=(),
            fall_rows=(),
            section_payloads=section_payloads,
            facts=facts,
            models=models,
            inferences=inferences,
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
        identity
        for row in our15_rows
        if (identity := player_id(row)) is not None
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
        section_payloads=section_payloads,
        facts=facts,
        models=models,
        inferences=inferences,
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
