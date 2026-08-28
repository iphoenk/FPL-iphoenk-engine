from __future__ import annotations

"""FAST/LIVE serving bundle preserving report_materializer ownership."""

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
