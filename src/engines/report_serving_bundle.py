from __future__ import annotations

"""FAST/LIVE consolidated report construction + serving bundle.

The report pipeline is one logical artifact owner in FAST/LIVE: decision-first
construction, report-time enrichment, serving materialization, transparency and
contract validation run in-process. FULL/DEEP retain the same stage order through
registry commands for conservative parity.
"""

import json

from src.engines import report_architecture
from src.engines import report_enrichment
from src.engines import report_materializer
from src.engines import report_transparency_overlay
from src.engines import report_serving_validate


def run() -> dict:
    constructed = report_architecture.run()
    enriched = report_enrichment.run()
    materialized = report_materializer.run()
    transparent = report_transparency_overlay.run()
    validated = report_serving_validate.run()
    return {
        "constructed": constructed,
        "enriched": enriched,
        "materialized": materialized,
        "transparent": transparent,
        "validated": validated,
    }


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": "PASS",
        "bundle": "report_serving",
        "single_logical_report_owner": True,
        "validation": (out.get("validated") or {}).get("status"),
    }, ensure_ascii=False))
