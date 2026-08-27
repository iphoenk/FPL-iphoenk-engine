from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "dss_operationalization.json"
EVIDENCE_PATH = DATA / "dss_operational_evidence.json"
HEALTH_PATH = DATA / "framework_health.json"


def _policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def classify_evidence_tier(detail: dict[str, Any] | None, status: str | None, policy: dict[str, Any]) -> str:
    maturity = policy.get("evidence_maturity") or {}
    allowed = set(maturity.get("tiers") or [])
    overrides = maturity.get("state_overrides") or {}
    evaluator_tiers = maturity.get("evaluator_available_tier") or {}
    detail = detail or {}
    evidence_state = str(detail.get("evidence_state") or "")
    evaluator = str(detail.get("evaluator") or "")

    if str(status or "") != "ACTIVE":
        tier = "UNAVAILABLE"
    elif evidence_state in overrides:
        tier = str(overrides[evidence_state])
    else:
        tier = str(evaluator_tiers.get(evaluator) or "DERIVED")

    if tier not in allowed:
        raise RuntimeError(f"invalid evidence maturity tier: {tier}")
    return tier


def run() -> dict[str, Any]:
    policy = _policy()
    maturity = policy.get("evidence_maturity") or {}
    allowed = list(maturity.get("tiers") or [])
    if allowed != ["NATIVE", "DERIVED", "PROXY", "SAFE_FALLBACK", "UNAVAILABLE"]:
        raise RuntimeError("unexpected evidence maturity tier contract")

    evidence = read_json(EVIDENCE_PATH, {})
    rows = list(evidence.get("evaluated") or [])
    counts: Counter[str] = Counter()
    for row in rows:
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        tier = classify_evidence_tier(detail, row.get("status"), policy)
        row["evidence_tier"] = tier
        if isinstance(row.get("detail"), dict):
            row["detail"]["evidence_tier"] = tier
        counts[tier] += 1

    evidence["evaluated"] = rows
    evidence["evidence_maturity"] = {
        "tiers": allowed,
        "counts": {tier: int(counts.get(tier, 0)) for tier in allowed},
        "module_health_separate": True,
        "active_does_not_imply_native_evidence": True,
    }
    atomic_json(EVIDENCE_PATH, evidence)

    health = read_json(HEALTH_PATH, {})
    health.setdefault("dss_operationalization", {})["evidence_maturity"] = evidence["evidence_maturity"]
    health.setdefault("governance", {}).update({
        "evidence_maturity_is_separate_from_module_health": True,
        "active_dss_does_not_imply_native_evidence": True,
    })
    atomic_json(HEALTH_PATH, health)

    latest = read_json(DATA / "latest.json", {})
    latest["dss_evidence_maturity"] = evidence["evidence_maturity"]
    atomic_json(DATA / "latest.json", latest)

    print(json.dumps(evidence["evidence_maturity"], ensure_ascii=False))
    return evidence


if __name__ == "__main__":
    run()
