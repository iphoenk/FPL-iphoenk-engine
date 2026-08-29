from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

CONFIG = ROOT / "config" / "sources" / "external_benchmark_consensus.json"
INPUT = DATA / "external_benchmark_observations.json"
OUTPUT = DATA / "external_consensus.json"


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _source_map(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in cfg.get("sources") or []}


def _native_snapshot() -> dict[str, Any]:
    lineup = read_json(DATA / "lineup_decision.json", {})
    package = read_json(DATA / "package_decision.json", {})
    report = read_json(DATA / "user_report.json", {})
    return {
        "planning_gw": lineup.get("planning_gw"),
        "formation": lineup.get("formation"),
        "starting_xi": list(lineup.get("starting_xi") or []),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "package_id": package.get("selected_package_id") or package.get("id"),
        "report_decision": (report.get("decision") or {}).get("overall"),
    }


def _normalize(row: dict[str, Any], source_cfg: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    allowed_availability = set(cfg.get("availability_states") or [])
    allowed_directions = set(cfg.get("directions") or [])
    availability = str(row.get("availability") or "UNAVAILABLE")
    if availability not in allowed_availability:
        availability = "UNAVAILABLE"
    direction = str(row.get("normalized_direction") or "INSUFFICIENT_EVIDENCE")
    if direction not in allowed_directions:
        direction = "INSUFFICIENT_EVIDENCE"
    if availability in {"UNAVAILABLE", "STALE", "NO_MATERIAL_UPDATE"}:
        direction = "INSUFFICIENT_EVIDENCE" if availability != "NO_MATERIAL_UPDATE" else "NEUTRAL"
    return {
        "source": str(row.get("source") or source_cfg.get("id") or "unknown"),
        "source_role": str(row.get("source_role") or source_cfg.get("role") or "UNKNOWN"),
        "observed_at": row.get("observed_at"),
        "freshness": row.get("freshness"),
        "availability": availability,
        "subject": row.get("subject"),
        "horizon": row.get("horizon"),
        "signal": row.get("signal"),
        "native_metric_if_visible": row.get("native_metric_if_visible"),
        "normalized_direction": direction,
        "confidence": row.get("confidence"),
        "evidence_note": row.get("evidence_note"),
        "possible_factual_error": bool(row.get("possible_factual_error")),
    }


def _subject_classification(rows: list[dict[str, Any]]) -> str:
    current = [r for r in rows if r.get("availability") in {"AVAILABLE", "PARTIAL"}]
    directions = {str(r.get("normalized_direction")) for r in current}
    if not current:
        return "INSUFFICIENT_EVIDENCE"
    if directions <= {"SUPPORT_NATIVE", "NEUTRAL"} and "SUPPORT_NATIVE" in directions:
        return "ALIGN"
    if directions <= {"OPPOSE_NATIVE", "NEUTRAL"} and "OPPOSE_NATIVE" in directions:
        return "DIVERGE"
    if "SUPPORT_NATIVE" in directions and "OPPOSE_NATIVE" in directions:
        return "REVIEW_DIVERGENCE"
    return "NEUTRAL"


def build_consensus(observations: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _load_config()
    source_map = _source_map(cfg)
    payload = observations if observations is not None else read_json(INPUT, {})
    raw_rows = list(payload.get("observations") or [])
    normalized: list[dict[str, Any]] = []
    for row in raw_rows:
        source_id = str(row.get("source") or row.get("source_id") or "")
        source_cfg = source_map.get(source_id)
        if source_cfg is None:
            continue
        normalized.append(_normalize(row, source_cfg, cfg))

    subjects: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        subject = str(row.get("subject") or "UNSPECIFIED")
        subjects.setdefault(subject, []).append(row)

    subject_results = [
        {"subject": subject, "classification": _subject_classification(rows), "observations": rows}
        for subject, rows in sorted(subjects.items())
    ]
    current_rows = [r for r in normalized if r.get("availability") in {"AVAILABLE", "PARTIAL"}]
    factual_refresh = any(r.get("possible_factual_error") for r in current_rows)
    if not current_rows:
        overall = "INSUFFICIENT_EVIDENCE"
    elif any(r["classification"] == "REVIEW_DIVERGENCE" for r in subject_results):
        overall = "REVIEW_DIVERGENCE"
    elif any(r["classification"] == "DIVERGE" for r in subject_results):
        overall = "DIVERGE"
    elif any(r["classification"] == "ALIGN" for r in subject_results):
        overall = "ALIGN"
    else:
        overall = "NEUTRAL"

    result = {
        "schema_version": 1,
        "contract": "EXTERNAL_CONSENSUS_V1",
        "generated_at": iso_now(),
        "owner": cfg.get("owner"),
        "authority": cfg.get("authority"),
        "native_conclusion_frozen_before_overlay": True,
        "native_snapshot": _native_snapshot(),
        "overall": overall,
        "requires_official_refresh": factual_refresh,
        "observations": normalized,
        "subjects": subject_results,
        "source_status": {
            source_id: next(
                (r.get("availability") for r in normalized if r.get("source") == source_id),
                "UNAVAILABLE",
            )
            for source_id in source_map
        },
        "governance": {
            "advisory_only": True,
            "majority_vote_used": False,
            "native_truth_mutated": False,
            "outage_fail_neutral": True,
            "external_network_calls_in_warm_path": False,
            "factual_divergence_action": "REFRESH_OFFICIAL_AND_RERUN_NATIVE" if factual_refresh else "NONE",
        },
    }
    return result


def run() -> dict[str, Any]:
    result = build_consensus()
    atomic_json(OUTPUT, result)
    latest = read_json(DATA / "latest.json", {})
    latest["external_consensus_summary"] = {
        "overall": result.get("overall"),
        "observation_count": len(result.get("observations") or []),
        "requires_official_refresh": result.get("requires_official_refresh"),
        "advisory_only": True,
    }
    latest.setdefault("files", {})["external_consensus"] = "data/external_consensus.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["external_consensus_summary"], ensure_ascii=False))
    return result


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
