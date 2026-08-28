import pytest

from src.v5.config_cache import load_json_config
from src.v5.intelligence.feature_fusion import fuse_advanced_attack
from src.v5.intelligence.full_core_enrichment import _advanced_freshness, build_full_core_enrichment
from src.v5.services.prediction import _bind_advanced_freshness_context


def _advanced_cfg():
    return load_json_config("config/intelligence/evidence_enrichment.json")["advanced_stats"]


def _fusion_cfg():
    return load_json_config("config/intelligence/projection.json")["authoritative_feature_fusion"]


def _artifact(gw: int):
    return {"gw": gw, "fetched_at": "2026-08-25T12:33:22+00:00", "rows": [{}]}


def test_planning_gw2_accepts_gw1_as_last_completed_evidence():
    freshness = _advanced_freshness(_advanced_cfg(), _artifact(1), _artifact(1), planning_gw=2)
    assert freshness["status"] == "CURRENT_COMPLETED_GW"
    assert freshness["expected_completed_gw"] == 1
    assert freshness["artifact_gw"] == 1
    assert freshness["gw_lag"] == 0
    assert freshness["authoritative_eligible"] is True


def test_planning_gw3_rejects_stale_gw1_evidence():
    freshness = _advanced_freshness(_advanced_cfg(), _artifact(1), _artifact(1), planning_gw=3)
    assert freshness["status"] == "STALE_GW"
    assert freshness["expected_completed_gw"] == 2
    assert freshness["artifact_gw"] == 1
    assert freshness["gw_lag"] == 1
    assert freshness["authoritative_eligible"] is False


def test_future_or_mismatched_artifacts_are_not_authoritative():
    future = _advanced_freshness(_advanced_cfg(), _artifact(2), _artifact(2), planning_gw=2)
    mismatch = _advanced_freshness(_advanced_cfg(), _artifact(1), _artifact(2), planning_gw=3)
    assert future["status"] == "FUTURE_DATA_BLOCKED"
    assert future["authoritative_eligible"] is False
    assert mismatch["status"] == "ARTIFACT_GW_MISMATCH"
    assert mismatch["authoritative_eligible"] is False


def test_real_gw1_artifacts_are_current_for_planning_gw2_and_stale_for_gw3():
    bootstrap = {"elements": [], "teams": []}
    source_fusion = {"status": "UNAVAILABLE", "sources": {}}
    gw2 = build_full_core_enrichment(bootstrap, [], source_fusion, planning_gw=2)
    gw3 = build_full_core_enrichment(bootstrap, [], source_fusion, planning_gw=3)
    assert gw2["advanced_stats"]["artifact_gw"] == 1
    assert gw2["advanced_stats"]["authoritative_eligible"] is True
    assert gw2["advanced_stats"]["freshness"]["status"] == "CURRENT_COMPLETED_GW"
    assert gw3["advanced_stats"]["artifact_gw"] == 1
    assert gw3["advanced_stats"]["authoritative_eligible"] is False
    assert gw3["advanced_stats"]["freshness"]["status"] == "STALE_GW"


def test_prediction_binding_embeds_single_enrichment_authority_context():
    enrichment = {
        "advanced_stats": {
            "authoritative_eligible": False,
            "freshness": {"status": "STALE_GW", "reason": "stale"},
            "players": {"1": {"minutes": 90.0, "xg": 1.0, "xa": 0.5}},
        }
    }
    _bind_advanced_freshness_context(enrichment)
    context = enrichment["advanced_stats"]["players"]["1"]["_source_context"]
    assert context["authoritative_eligible"] is False
    assert context["freshness"]["status"] == "STALE_GW"


def test_stale_advanced_evidence_remains_available_but_cannot_change_rate():
    result = fuse_advanced_attack(
        position="MID",
        native_xg90=0.20,
        native_xa90=0.10,
        position_xg_prior=0.22,
        position_xa_prior=0.20,
        advanced={
            "minutes": 90,
            "xg": 2.0,
            "xa": 1.0,
            "_source_context": {
                "authoritative_eligible": False,
                "freshness": {
                    "status": "STALE_GW",
                    "reason": "advanced artifact is older than the configured authoritative gameweek lag",
                },
            },
        },
        config=_fusion_cfg(),
    )
    assert result["status"] == "AVAILABLE_NOT_APPLIED"
    assert result["applied"] is False
    assert result["source_authoritative_eligible"] is False
    assert result["source_freshness"]["status"] == "STALE_GW"
    assert result["xg90_final"] == pytest.approx(0.20)
    assert result["xa90_final"] == pytest.approx(0.10)
