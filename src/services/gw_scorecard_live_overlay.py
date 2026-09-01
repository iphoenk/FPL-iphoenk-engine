from __future__ import annotations

import json

from src.services import gw_scorecard_service
from src.services.match_mode_live_score import build_match_mode_scorecard
from src.utils import DATA, atomic_json, read_json

SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
OUTFILE = DATA / "gw_scorecard_v4.json"


def run() -> dict:
    """Extend the existing personal-GW boundary with governed Match Mode facts.

    This is composition inside the existing service boundary, not a ninth runtime
    microservice and not a second decision authority.
    """
    out = gw_scorecard_service.run()
    raw = read_json(SNAPSHOT, {})
    live = build_match_mode_scorecard(raw)
    out["current_live_gw"] = live
    out.setdefault("guardrails", {}).update({
        "match_mode_live_score_inside_existing_scorecard_boundary": True,
        "match_mode_all15_required_when_official_available": True,
        "submitted_picks_are_match_mode_scoring_authority": True,
        "planning_xi_cannot_replace_submitted_match_mode_picks": True,
        "actual_vs_predicted_is_diagnostic_only": True,
    })
    atomic_json(OUTFILE, out)
    return out


if __name__ == "__main__":
    result = run()
    live = result.get("current_live_gw") or {}
    print(json.dumps({
        "service": "personal_gw_scorecard",
        "status": result.get("status"),
        "match_mode": live.get("status"),
        "owned_live_coverage": (live.get("coverage") or {}).get("owned"),
    }, ensure_ascii=False))
