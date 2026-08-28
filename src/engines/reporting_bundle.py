from __future__ import annotations

"""FAST/LIVE report construction bundle.

Keeps `reporting` as one logical artifact owner while avoiding a second Python
interpreter startup between architecture and enrichment.
"""

import json

from src.engines import report_architecture
from src.engines import report_enrichment


def run() -> dict:
    base = report_architecture.run()
    enriched = report_enrichment.run()
    return {"base": base, "enriched": enriched}


if __name__ == "__main__":
    out = run()
    print(json.dumps({"status": "PASS", "bundle": "reporting"}, ensure_ascii=False))
