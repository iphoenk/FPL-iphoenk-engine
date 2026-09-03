from __future__ import annotations

from src.engines import v4_full_universe_package_search as search


def _raw_result(proofs):
    return {
        "search": {"pruning_proofs": proofs},
        "overall_verdict": "MATERIAL_UPGRADE",
        "recommended_package": {"replacements": 1},
        "best_by_replacement_count": {"1": {"replacements": 1}},
        "packages": {"1": [{"replacements": 1}]},
        "efficient_frontier": {"status": "PASS", "packages": [{"replacements": 1}]},
        "governance": {},
    }


def test_authority_gate_preserves_proven_result():
    out = search._apply_authority_gate(_raw_result([]), global_proof=True)
    assert out["search"]["authoritative_for_recommendation"] is True
    assert out["best_by_replacement_count"] is not None
    assert out["recommended_package"] is not None
    assert out["decision_authority"] == "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"


def test_authority_gate_blocks_heuristic_result_from_canonical_consumers():
    out = search._apply_authority_gate(_raw_result([]), global_proof=False)
    assert out["search"]["authoritative_for_recommendation"] is False
    assert out["decision_authority"] == "BLOCKED_HEURISTIC_SEARCH"
    assert out["overall_verdict"] == "FULL_UNIVERSE_HEURISTIC"
    assert out["best_by_replacement_count"] is None
    assert out["recommended_package"] is None
    assert out["packages"] == {}
    assert out["heuristic_discovery"]["overall_verdict"] == "MATERIAL_UPGRADE"
    assert out["heuristic_discovery"]["recommended_package"]["replacements"] == 1
    assert out["governance"]["heuristic_discovery_is_diagnostic_only"] is True
    assert out["governance"]["canonical_recommendation_fields_fail_closed"] is True
