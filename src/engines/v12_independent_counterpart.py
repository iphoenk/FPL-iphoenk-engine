"""Independent advisory counterpart analysis for V12 decisions.

Does not alter canonical football models or simulate missing evidence.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/intelligence/v12_independent_counterpart_v1.json"


def load_counterpart_policy() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def assess_counterpart(
    canonical: Mapping[str, Any],
    counterparts: list[Mapping[str, Any]],
    *,
    relative_gap_threshold: float = 0.20,
) -> dict[str, Any]:
    """Compare like-for-like metrics; fail closed on missing/old/linked sources.

    An independent source can challenge the recommendation, never rewrite it.
    """
    subject = str(canonical.get("subject") or "")
    metric = str(canonical.get("metric") or "")
    value = canonical.get("value")
    as_of = str(canonical.get("as_of") or "")
    deadline = str(canonical.get("deadline") or "")
    evidence: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    if not subject or not metric or value is None or not as_of or not deadline:
        return {"subject": subject, "metric": metric, "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": "CANONICAL_PROVENANCE_MISSING", "comparisons": [], "rejected": []}
    try:
        base = float(value)
    except (ValueError, TypeError):
        return {"subject": subject, "metric": metric, "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": "CANONICAL_VALUE_INVALID", "comparisons": [], "rejected": []}
    seen_groups: set[str] = set()
    for raw in counterparts:
        row = dict(raw)
        name = str(row.get("source") or "")
        group = str(row.get("independence_group") or "")
        date = str(row.get("as_of") or "")
        counterpart_metric = str(row.get("metric") or "")
        if not name or not group or not date or date > deadline or date > as_of:
            rejected.append({"source": name, "reason": "SOURCE_PROVENANCE_OR_TEMPORAL_INVALID"})
            continue
        if group in seen_groups or group == str(canonical.get("independence_group") or ""):
            rejected.append({"source": name, "reason": "NOT_DISTINCT_INDEPENDENCE_GROUP"})
            continue
        if counterpart_metric != metric or str(row.get("horizon") or "") != str(canonical.get("horizon") or ""):
            rejected.append({"source": name, "reason": "INCOMPATIBLE_METRIC_OR_HORIZON"})
            continue
        try:
            other = float(row["value"])
        except (ValueError, TypeError, KeyError):
            rejected.append({"source": name, "reason": "INVALID_VALUE"})
            continue
        seen_groups.add(group)
        delta = base - other
        evidence.append({"source": name, "independence_group": group,
                         "as_of": date, "canonical_value": base,
                         "counterpart_value": other, "delta": delta,
                         "relative_gap": abs(delta) / max(abs(other), 1.0)})
    if not evidence:
        verdict, reason = "INSUFFICIENT_EVIDENCE", "NO_COMPARABLE_INDEPENDENT_SOURCE"
    elif any(r["relative_gap"] > relative_gap_threshold for r in evidence):
        verdict, reason = "CONTESTED", "MATERIAL_INDEPENDENT_DISAGREEMENT"
    else:
        verdict, reason = "CONFIRMED", "COMPARABLE_INDEPENDENT_SUPPORT"
    return {"subject": subject, "metric": metric, "verdict": verdict, "reason": reason,
            "comparisons": evidence, "rejected": rejected, "canonical_unchanged": True}
