from __future__ import annotations

"""FAST/LIVE final report-serving bundle.

Decision-report construction remains owned by the reporting service. This bundle
owns only final materialization, transparency decoration and serving validation,
so the two logical report capabilities do not execute each other's functions.
"""

import json

from src.engines import report_materializer
from src.engines import report_transparency_overlay
from src.engines import report_serving_validate


def run() -> dict:
    materialized = report_materializer.run()
    transparent = report_transparency_overlay.run()
    validated = report_serving_validate.run()
    return {
        "materialized": materialized,
        "transparent": transparent,
        "validated": validated,
    }


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": "PASS",
        "bundle": "report_serving",
        "validation": (out.get("validated") or {}).get("status"),
    }, ensure_ascii=False))
