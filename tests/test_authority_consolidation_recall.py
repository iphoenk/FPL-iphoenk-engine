from __future__ import annotations

import json
from pathlib import Path


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "authority_consolidation"
    / "runtime_recall_pre_v11_1.json"
)

REQUIRED_RECALL_STAGES = (
    "DECISION CONTEXT HYDRATION",
    "ACQUISITION / TERMINAL CONTINUATION",
    "EXACT REPORT-PREFETCH CHECK / RECOVERY",
    "DELIVERY_ACKNOWLEDGED",
    "IMMUTABLE SAME-SLOT RECEIPT",
)


def test_pre_v11_recall_contains_terminal_report_completion_chain():
    """Intentional TDD RED: proves the pre-V1.1 condensed recall is incomplete."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    recall = payload["final_execution_recall"]
    missing = [stage for stage in REQUIRED_RECALL_STAGES if stage not in recall]
    assert not missing, f"FINAL EXECUTION RECALL drift: missing {missing}"
