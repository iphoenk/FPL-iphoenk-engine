from __future__ import annotations

import json

from src.engines import rules_compliance_audit


def refresh_if_due() -> dict:
    """Compatibility wrapper around the canonical rules auditor owner."""
    return rules_compliance_audit.refresh_if_due()


def main() -> int:
    result = refresh_if_due()
    print(json.dumps(result, ensure_ascii=False))
    return 3 if result.get("status") == "MANUAL_REVIEW_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
