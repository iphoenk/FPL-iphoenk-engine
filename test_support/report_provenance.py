from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from test_support.report_sections import r4_section_payloads


def canonical_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def source_snapshot_id(source: str, token: str) -> str:
    return f"{source}:payload:{sha256(token.encode('utf-8')).hexdigest()}"


def fact_row(*, source: str, token: str, value: Any = None) -> dict[str, Any]:
    row = {
        "source": source,
        "effective_at": "2026-09-16T21:30:00+00:00",
        "source_snapshot_ids": [source_snapshot_id(source.lower(), token)],
    }
    if value is not None:
        row["value"] = value
    return row


def model_row(
    *,
    model: str,
    input_snapshot_ids: Sequence[str],
    value: Any = None,
) -> dict[str, Any]:
    row = {
        "model": model,
        "computed_at": "2026-09-16T21:31:00+00:00",
        "input_snapshot_ids": list(input_snapshot_ids),
    }
    if value is not None:
        row["value"] = value
    return row


def inference_row(
    *,
    fact_refs: Sequence[str],
    model_refs: Sequence[str],
    value: Any = "WAIT",
    basis: str = "FACT_AND_MODEL",
) -> dict[str, Any]:
    return {
        "basis": basis,
        "fact_refs": list(fact_refs),
        "model_refs": list(model_refs),
        "value": value,
    }


def r5_partitions(
    *,
    fact_key: str = "official",
    model_key: str = "projection",
    inference_key: str = "decision",
    fact_source: str = "OFFICIAL_FPL",
    model_name: str = "V6_MODEL",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fact = fact_row(source=fact_source, token=fact_key, value=True)
    weather = fact_row(source="OPEN_METEO", token="weather", value="NORMAL")
    facts = {fact_key: fact, "weather_forecast": weather}
    models = {
        model_key: model_row(
            model=model_name,
            input_snapshot_ids=fact["source_snapshot_ids"],
            value=1.0,
        )
    }
    inferences = {
        inference_key: inference_row(
            fact_refs=[fact_key],
            model_refs=[model_key],
        )
    }
    return facts, models, inferences


def r5_section_payloads(our15_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sections = r4_section_payloads(our15_rows)
    sections["WEATHER"]["source_proof"] = {
        "source": "OPEN_METEO",
        "effective_at": "2026-09-16T21:30:00+00:00",
        "source_snapshot_ids": [source_snapshot_id("open_meteo", "weather")],
    }

    routes = sections["OPTIMIZER"]["routes"]
    optimizer_input = {
        "our15_ids": [
            row.get("element_id") or row.get("player_id") or row.get("id")
            for row in our15_rows
        ]
    }
    route_summary = {
        "route_ids": [
            row.get("route_id") if isinstance(row, Mapping) else None
            for row in routes
        ]
    }
    sections["OPTIMIZER"]["execution_proof"] = {
        "optimizer": {
            "state": "EXECUTED",
            "run_id": "optimizer-run-fixture",
            "method": "MULTI_HORIZON_PACKAGE_OPTIMIZER",
            "executed_at": "2026-09-16T21:32:00+00:00",
            "input_fingerprint": canonical_digest(optimizer_input),
            "output_fingerprint": canonical_digest(routes),
        },
        "monte_carlo": {
            "state": "EXECUTED",
            "run_id": "mc-run-fixture",
            "method": "MONTE_CARLO",
            "executed_at": "2026-09-16T21:32:30+00:00",
            "input_fingerprint": canonical_digest(optimizer_input),
            "output_fingerprint": canonical_digest(route_summary),
            "actual_paths": 500000,
        },
        "frontier": {
            "state": "PARTIAL",
            "run_id": "frontier-run-fixture",
            "method": "SEARCH_FRONTIER",
            "executed_at": "2026-09-16T21:32:45+00:00",
            "input_fingerprint": canonical_digest(optimizer_input),
            "output_fingerprint": canonical_digest(route_summary),
            "degradation_reason": "LOSSY_SEARCH_FRONTIER",
        },
    }
    return sections
