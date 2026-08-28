from __future__ import annotations

"""FAST/LIVE watchlist bundle preserving the existing logical service contract."""

import json

from src.engines import dss_watchlist
from src.engines import watchlist_public_sanitize


def run() -> dict:
    screened = dss_watchlist.run()
    public = watchlist_public_sanitize.run()
    return {"screened": screened, "public": public}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": "PASS",
        "bundle": "watchlist",
        "published": ((out.get("screened") or {}).get("published")
                      or sum(len(rows) for rows in ((out.get("screened") or {}).get("positions") or {}).values())),
    }, ensure_ascii=False))
