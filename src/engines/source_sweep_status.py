from __future__ import annotations

from src.utils import CONFIG, DATA, read_json

POLICY = CONFIG / "checkpoint_policy_registry.json"
ADAPTERS = CONFIG / "source_adapter_registry.json"
UNDERSTAT = DATA / "understat_tactical_v4.json"


def _understat_status() -> tuple[str, str]:
    payload = read_json(UNDERSTAT, {}) or {}
    health = payload.get("health") or {}
    source = payload.get("source") or {}
    if not payload:
        return "UNAVAILABLE", "understat_runtime_artifact_missing"
    freshness = str(source.get("freshness") or "UNKNOWN").upper()
    availability = str(source.get("availability") or "UNAVAILABLE").upper()
    native = str(health.get("status") or "UNAVAILABLE").upper()
    if freshness in {"STALE", "EXPIRED"} or availability == "STALE_FALLBACK":
        status = "STALE"
    elif native == "AVAILABLE":
        status = "AVAILABLE"
    elif native == "PARTIAL":
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"
    evidence = (
        f"data/understat_tactical_v4.json health={native} freshness={freshness} "
        f"mapped={health.get('player_mapping_count')} coverage={health.get('tactical_matchup_coverage')}"
    )
    return status, evidence


def build_source_sweep_status(endpoint_health: dict | None = None, external_evidence: dict | None = None) -> dict:
    """Resolve truthful Tier 1-5 source status without inventing adapter availability."""
    policy = read_json(POLICY, {})
    adapters = read_json(ADAPTERS, {})
    endpoint_health = endpoint_health or {}
    external_evidence = external_evidence or {}
    allowed = set(adapters.get("allowed_statuses") or [])
    tiers = (policy.get("source_sweep") or {}).get("tiers") or {}
    configured = adapters.get("sources") or {}
    rows = []
    missing = []

    for tier, source_ids in tiers.items():
        for source_id in source_ids:
            adapter = configured.get(source_id)
            if not adapter:
                missing.append(source_id)
                rows.append({"source_id": source_id, "tier": int(tier), "status": "UNAVAILABLE", "runtime_wired": False, "evidence": "adapter_registry_missing"})
                continue

            evidence = external_evidence.get(source_id)
            if evidence:
                status = str(evidence.get("status") or "UNAVAILABLE").upper()
                if status not in allowed:
                    raise RuntimeError(f"invalid external source status {status} for {source_id}")
                rows.append({
                    "source_id": source_id,
                    "tier": int(tier),
                    "status": status,
                    "runtime_wired": bool(adapter.get("runtime_wired")),
                    "evidence": evidence.get("evidence") or "external_report_time_sweep",
                })
                continue

            if source_id == "official_fpl_native":
                health_rows = [row for row in endpoint_health.values() if isinstance(row, dict)]
                statuses = {str(row.get("status") or "").upper() for row in health_rows}
                if "FAILED" in statuses:
                    status = "PARTIAL" if "LIVE" in statuses else "UNAVAILABLE"
                elif "LIVE" in statuses:
                    status = "AVAILABLE"
                else:
                    status = "UNAVAILABLE"
                evidence_text = "raw_snapshot.endpoint_health"
            elif source_id == "understat_tactical":
                status, evidence_text = _understat_status()
            else:
                status = "UNAVAILABLE"
                evidence_text = "no_runtime_adapter_or_external_sweep_evidence"

            rows.append({
                "source_id": source_id,
                "tier": int(tier),
                "status": status,
                "runtime_wired": bool(adapter.get("runtime_wired")),
                "evidence": evidence_text,
            })

    if missing:
        raise RuntimeError(f"source adapter registry incomplete: {sorted(missing)}")
    invalid = [row for row in rows if row["status"] not in allowed]
    if invalid:
        raise RuntimeError(f"source sweep produced invalid statuses: {invalid}")

    by_tier = {}
    for tier in sorted({row["tier"] for row in rows}):
        tier_rows = [row for row in rows if row["tier"] == tier]
        by_tier[str(tier)] = {
            "sources": tier_rows,
            "available": sum(row["status"] == "AVAILABLE" for row in tier_rows),
            "partial": sum(row["status"] == "PARTIAL" for row in tier_rows),
            "unavailable": sum(row["status"] == "UNAVAILABLE" for row in tier_rows),
            "stale": sum(row["status"] == "STALE" for row in tier_rows),
        }

    return {
        "registry": adapters.get("registry"),
        "fabrication_forbidden": bool(adapters.get("fabrication_forbidden")),
        "statuses": rows,
        "by_tier": by_tier,
        "all_governance_sources_accounted_for": True,
        "runtime_wired_sources": [row["source_id"] for row in rows if row["runtime_wired"]],
        "external_evidence_sources": sorted(external_evidence),
    }
