from __future__ import annotations

import json
from typing import Any

from src.engines import rules_compliance_audit

REMOTE_REFRESH_DUE_STATES = frozenset({"NOT_RUN", "STALE"})


def refresh_if_due() -> dict[str, Any]:
    """Refresh remote rules evidence only when the governed cached state is due.

    The rules compliance auditor remains the single owner of freshness thresholds,
    remote fingerprints and change semantics. This runtime hook only decides
    whether to request a remote audit from the state returned by that owner.
    REVIEW_REQUIRED is deliberately never auto-cleared by a follow-up refresh.
    """
    cached = rules_compliance_audit.audit(check_remote=False)
    drift = cached.get("drift") or {}
    before = str(drift.get("status") or "NOT_RUN")

    if before == "REVIEW_REQUIRED":
        return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "remote_check_executed": False,
            "drift_before": before,
            "drift_after": before,
            "rules_overall": cached.get("overall"),
        }

    if before not in REMOTE_REFRESH_DUE_STATES:
        return {
            "status": "FRESH",
            "remote_check_executed": False,
            "drift_before": before,
            "drift_after": before,
            "rules_overall": cached.get("overall"),
        }

    refreshed = rules_compliance_audit.audit(check_remote=True)
    after = str((refreshed.get("drift") or {}).get("status") or "UNKNOWN")
    return {
        "status": "REFRESHED",
        "remote_check_executed": True,
        "drift_before": before,
        "drift_after": after,
        "rules_overall": refreshed.get("overall"),
    }


def main() -> int:
    print(json.dumps(refresh_if_due(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
