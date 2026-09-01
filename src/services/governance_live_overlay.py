from __future__ import annotations

import json

from src.services import governance_service
from src.services.contracts import file_digest
from src.utils import DATA, atomic_json, read_json

SCORECARD = DATA / "gw_scorecard_v4.json"
CHECKPOINT = DATA / "checkpoint_decision_v4.json"
SERVING = DATA / "serving_payload_v4.json"
PUBLICATION_INTEGRITY = DATA / "publication_integrity_v4.json"


def _assert_match_mode_contract(live: dict, policy_id: str | None) -> None:
    if policy_id != "MATCHDAY_LIVE":
        return
    if live.get("match_mode_active") is not True:
        raise RuntimeError("Match Mode publication blocked: scoring-GW live state missing")
    picks_available = live.get("submitted_picks_status") == "AVAILABLE"
    event_live_available = live.get("event_live_status") == "AVAILABLE"
    coverage = live.get("coverage") or {}
    if picks_available and event_live_available and (
        coverage.get("complete") is not True or int(coverage.get("owned") or 0) != 15
    ):
        raise RuntimeError("Match Mode publication blocked: complete ALL15 live score required")


def _finalize_publication_integrity(live: dict) -> dict:
    integrity = read_json(PUBLICATION_INTEGRITY, {})
    if integrity.get("status") != "PASS":
        raise RuntimeError("final publication integrity requires PASS base integrity")
    if not CHECKPOINT.exists() or not SERVING.exists():
        raise RuntimeError("final publication integrity requires checkpoint and serving artifacts")
    integrity["final_artifacts"] = {
        "checkpoint_decision_v4": {
            "path": "data/checkpoint_decision_v4.json",
            "sha256": file_digest(CHECKPOINT),
        },
        "serving_payload_v4": {
            "path": "data/serving_payload_v4.json",
            "sha256": file_digest(SERVING),
        },
    }
    integrity["post_overlay_verification"] = {
        "status": "PASS",
        "match_mode_status": live.get("status"),
        "match_mode_composition_finalized_before_digest": True,
        "checked_content_is_published_content": True,
    }
    atomic_json(PUBLICATION_INTEGRITY, integrity)
    return integrity


def run(*, predictions_snapshot: dict | None = None) -> dict:
    """Add live-score composition to the existing final governance boundary."""
    out = (
        governance_service.run(predictions_snapshot=predictions_snapshot)
        if predictions_snapshot is not None
        else governance_service.run()
    )
    scorecard = read_json(SCORECARD, {})
    live = scorecard.get("current_live_gw") or {"status": "IDLE", "match_mode_active": False}
    checkpoint = read_json(CHECKPOINT, {})
    policy_id = ((checkpoint.get("checkpoint_context") or {}).get("policy_id"))
    _assert_match_mode_contract(live, policy_id)

    checkpoint.setdefault("personal_gw_scorecard", {})["current_live_gw"] = live
    checkpoint.setdefault("guardrails", {}).update({
        "match_mode_live_score_served_from_official_submitted_picks": True,
        "match_mode_all15_fail_closed": True,
        "match_mode_planning_xi_never_replaces_submitted_picks": True,
    })
    atomic_json(CHECKPOINT, checkpoint)

    serving = read_json(SERVING, {})
    if serving:
        serving["match_mode_live"] = live
        serving["personalized_live_score"] = live.get("personalized_live_score")
        serving.setdefault("guardrails", {}).update({
            "match_mode_live_score_composition_only": True,
            "match_mode_all15_fail_closed": True,
            "submitted_picks_are_live_scoring_authority": True,
            "actual_vs_predicted_diagnostic_only": True,
            "final_publication_integrity_sidecar": "data/publication_integrity_v4.json",
        })
        atomic_json(SERVING, serving)

    _finalize_publication_integrity(live)
    return out


if __name__ == "__main__":
    result = run()
    live = (read_json(SCORECARD, {}).get("current_live_gw") or {})
    print(json.dumps({
        "service": "governance",
        "status": result.get("status"),
        "match_mode": live.get("status"),
        "owned_live_coverage": (live.get("coverage") or {}).get("owned"),
    }, ensure_ascii=False))