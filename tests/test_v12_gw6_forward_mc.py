"""Unit acceptance for private GW6 striker what-if MC entrypoint.

Fake optimizer/MC here verify orchestration and fail-closed evidence; production
MC paths are never simulated by a test double or described as real results.
"""
import pytest
from src.engines.v12_gw6_forward_mc import WhatIfMCError, run_forward_mc

FORMATIONS = ("3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1")
OWNED = [346] + list(range(100, 114))


def _inputs():
    cfg = {
        "target_gw": 6,
        "baseline": {"slot": "2026-10-10T11:00:00+07:00"},
        "owned": [{"element_id": x} for x in OWNED],
    }
    projections = {
        "players": [{"element": x} for x in OWNED + [249, 569]],
        "model_evidence_binding": {"output_fingerprint": "test-fixture-only"},
    }
    warm = {
        "schema": "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1",
        "planning_gw": 6,
        "report_slot": cfg["baseline"]["slot"],
        "owned": [{"element_id": x} for x in OWNED],
        "projections": projections,
    }
    return cfg, warm


def _optimizer(projections, ids, *, planning_gw):
    xi = [{"element": x} for x in ids[:11]]
    bench = [{"element": x} for x in ids[11:]]
    return {
        "starting_xi": xi,
        "bench": {"order": bench[:3], "gk": bench[3]},
        "captain": xi[0], "vice_captain": xi[1],
        "formation": "5-4-1",
        "formation_comparison": [
            {"formation": f, "expected_fpl_points_with_captain_vice": 55.0}
            for f in FORMATIONS
        ],
    }


def _simulation(projections, routes, **kwargs):
    assert kwargs["actual_paths"] == 500_000
    assert kwargs["canonical"] is True
    assert kwargs["horizons"] == (1, 3, 5)
    assert len(routes) == 3
    for route in routes:
        assert [x["gw"] for x in route["per_gw"]] == [6, 7, 8, 9, 10]
        assert len(route["per_gw"][0]["starting_xi"]) == 11
    return {
        "execution_state": "EXECUTED", "canonical_pass": True,
        "actual_paths": 500_000, "output_fingerprint": "FAKE_TEST_ONLY",
        "metrics": {r["route_id"]: {"1": {}} for r in routes},
    }


def test_three_striker_scenarios_use_p17_and_mc_500k():
    cfg, warm = _inputs()
    result = run_forward_mc(cfg, warm, optimizer=_optimizer, simulator=_simulation)
    assert set(result["scenarios"]) == {"HOLD", "DCL_TO_BARRY", "DCL_TO_GONZALO"}
    assert result["mc_paths_each_route"] == 500_000
    assert result["finance"].startswith("UNAVAILABLE")
    assert result["private_publisher_called"] is False


def test_owner_current15_identity_must_match():
    cfg, warm = _inputs()
    warm["owned"][0]["element_id"] = 999
    with pytest.raises(WhatIfMCError, match="owned CURRENT15"):
        run_forward_mc(cfg, warm, optimizer=_optimizer, simulator=_simulation)


def test_same_occurrence_required():
    cfg, warm = _inputs()
    warm["report_slot"] = "2026-10-09T12:30:00+07:00"
    with pytest.raises(WhatIfMCError, match="same-occurrence"):
        run_forward_mc(cfg, warm, optimizer=_optimizer, simulator=_simulation)


def test_mc_convergence_cannot_be_faked():
    cfg, warm = _inputs()

    def failed(*args, **kwargs):
        result = _simulation(*args, **kwargs)
        result["canonical_pass"] = False
        return result

    with pytest.raises(WhatIfMCError, match="did not PASS"):
        run_forward_mc(cfg, warm, optimizer=_optimizer, simulator=failed)


def test_projection_binding_required():
    cfg, warm = _inputs()
    warm["projections"]["model_evidence_binding"] = {}
    with pytest.raises(WhatIfMCError, match="model evidence"):
        run_forward_mc(cfg, warm, optimizer=_optimizer, simulator=_simulation)


def test_incomplete_p17_starting_xi_fails():
    cfg, warm = _inputs()

    def incomplete(*args, **kwargs):
        lineup = _optimizer(*args, **kwargs)
        lineup["starting_xi"] = lineup["starting_xi"][:10]
        return lineup

    with pytest.raises(WhatIfMCError, match="completeness"):
        run_forward_mc(cfg, warm, optimizer=incomplete, simulator=_simulation)
