from __future__ import annotations

import pytest

import v4_frontier_regret_shadow as shadow


def _pkg(k, utility, xi, out_id, in_id):
    return {
        "replacements": k,
        "classification": "MATERIAL_UPGRADE",
        "adjusted_utility_gain_5": utility,
        "adjusted_best_xi_gain_5": xi,
        "delta_bench_adjusted_utility_5": utility,
        "delta_best_xi_xpts_5": xi,
        "target_itb": 0,
        "out": [{"element": out_id}],
        "in": [{"element": in_id}],
    }


def _report(width, *, k3_utility=25.73, k3_xi=25.44, k3_in=300, global_utility=30.68, global_xi=30.31, global_in=400):
    best = {
        "1": _pkg(1, 9.95, 9.96, 101, 201),
        "2": _pkg(2, 20.20, 19.83, 102, 202),
        "3": _pkg(3, k3_utility, k3_xi, 103, k3_in),
        "4": _pkg(4, global_utility, global_xi, 104, global_in),
    }
    return {
        "max_replacements": 4,
        "screened_players": 561,
        "frontier_players": width * 4,
        "overall_verdict": "MATERIAL_UPGRADE",
        "best_by_replacement_count": best,
        "recommended_package": best["4"],
        "performance": {"evaluated_packages": 1000 * width, "frontier_per_position": width},
        "guardrails": {"frontier_per_position": width},
    }


def _config(widths=None):
    return {
        "comparison_widths": widths or [7, 10, 13, 20],
        "max_replacements": 4,
        "top_per_size": 8,
        "beam_size": 28,
        "history_limit": 3,
        "regret_epsilon": 0.01,
    }


def test_shadow_detects_per_k_regret_without_claiming_global_winner_change(monkeypatch):
    reports = {
        7: _report(7),
        10: _report(10),
        13: _report(13, k3_utility=27.31, k3_xi=26.75, k3_in=313),
        20: _report(20, k3_utility=27.31, k3_xi=26.75, k3_in=313),
    }
    monkeypatch.setattr(shadow, "audit_packages_from_candidates", lambda *args, per_position_frontier, **kwargs: reports[per_position_frontier])

    out = shadow.frontier_regret_shadow_from_candidates(
        [],
        {},
        config=_config(),
        production_artifact=reports[7],
        source_snapshot={"predictions_generated_at": "snapshot-1"},
    )

    assert out["status"] == "PER_K_REGRET_OBSERVED"
    assert out["interpretation"]["per_k_regret_observed"] is True
    assert out["interpretation"]["global_regret_observed"] is False
    assert out["interpretation"]["global_optimum_stable_across_scanned_widths"] is True
    assert out["interpretation"]["search_complete_claim_supported"] is False
    assert out["by_width"]["13"]["per_replacement_count"]["3"]["utility_regret_vs_production"] == pytest.approx(1.58)
    assert out["production_parity"]["status"] == "PASS"
    assert out["decision_authority"] == "NONE"
    assert out["affects_search"] is False


def test_shadow_detects_global_regret(monkeypatch):
    reports = {
        7: _report(7),
        10: _report(10),
        13: _report(13, global_utility=31.25, global_xi=30.90, global_in=413),
        20: _report(20, global_utility=31.25, global_xi=30.90, global_in=413),
    }
    monkeypatch.setattr(shadow, "audit_packages_from_candidates", lambda *args, per_position_frontier, **kwargs: reports[per_position_frontier])

    out = shadow.frontier_regret_shadow_from_candidates([], {}, config=_config(), production_artifact=reports[7])

    assert out["status"] == "GLOBAL_REGRET_OBSERVED"
    assert out["interpretation"]["global_regret_observed"] is True
    assert out["interpretation"]["global_optimum_stable_across_scanned_widths"] is False
    assert out["by_width"]["13"]["global_winner"]["regret_observed"] is True


def test_shadow_records_no_regret_when_all_widths_are_semantically_equal(monkeypatch):
    reports = {width: _report(width) for width in [7, 10, 13, 20]}
    monkeypatch.setattr(shadow, "audit_packages_from_candidates", lambda *args, per_position_frontier, **kwargs: reports[per_position_frontier])

    out = shadow.frontier_regret_shadow_from_candidates([], {}, config=_config(), production_artifact=reports[7])

    assert out["status"] == "NO_REGRET_OBSERVED"
    assert out["interpretation"]["search_complete_claim_supported"] is True
    assert out["interpretation"]["max_utility_regret"] == 0.0
    assert out["guardrails"]["production_search_width_unchanged"] is True


def test_shadow_history_is_bounded(monkeypatch):
    reports = {width: _report(width) for width in [7, 10, 13, 20]}
    monkeypatch.setattr(shadow, "audit_packages_from_candidates", lambda *args, per_position_frontier, **kwargs: reports[per_position_frontier])
    previous = {"history": [{"generated_at": "1"}, {"generated_at": "2"}, {"generated_at": "3"}]}

    out = shadow.frontier_regret_shadow_from_candidates(
        [], {}, config=_config(), production_artifact=reports[7], previous_output=previous
    )

    assert len(out["history"]) == 3
    assert [row["generated_at"] for row in out["history"][:2]] == ["2", "3"]


def test_shadow_fails_closed_if_config_baseline_drifts_from_production_width():
    with pytest.raises(RuntimeError, match="does not match production frontier"):
        shadow.frontier_regret_shadow_from_candidates([], {}, config=_config([8, 10, 13, 20]))


def test_shadow_fails_closed_if_runtime_artifact_reports_different_production_width(monkeypatch):
    reports = {width: _report(width) for width in [7, 10, 13, 20]}
    monkeypatch.setattr(shadow, "audit_packages_from_candidates", lambda *args, per_position_frontier, **kwargs: reports[per_position_frontier])
    artifact = _report(7)
    artifact["performance"]["frontier_per_position"] = 8

    with pytest.raises(RuntimeError, match="disagrees with canonical width"):
        shadow.frontier_regret_shadow_from_candidates([], {}, config=_config(), production_artifact=artifact)
