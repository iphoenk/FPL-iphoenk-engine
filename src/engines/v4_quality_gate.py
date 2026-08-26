from __future__ import annotations

import json
import statistics
from pathlib import Path

from src.engines.reliability import validate_snapshot
from src.utils import DATA


def _load(name: str) -> dict:
    path = DATA / name
    if not path.exists():
        raise AssertionError(f"missing required quality-gate input: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _assert_framework_health() -> tuple[dict, dict]:
    pre = _load("framework_health_preflight_v4.json")
    post = _load("framework_health_v4.json")

    for obj, phase in ((pre, "preflight"), (post, "postflight")):
        assert int(obj.get("schema_version", 0)) >= 472, obj
        assert str(obj.get("engine", "")).startswith("v4.7.2-framework-health-performance-cache"), obj
        assert obj.get("phase") == phase, obj
        assert obj.get("registry_integrity") is True, obj
        assert obj.get("overall") in {"GREEN", "AMBER"}, obj
        assert obj.get("recommendation_allowed") is True, obj
        assert obj.get("go_allowed") is (obj.get("overall") == "GREEN"), obj
        assert obj.get("gate0", {}).get("pass") is True, obj.get("gate0")
        assert obj.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0, obj.get("gate0")
        assert obj.get("dss_core", {}).get("declared") == 50 and obj["dss_core"].get("integrity_ok") is True
        assert obj.get("dss_extensions", {}).get("declared") == 16 and obj["dss_extensions"].get("integrity_ok") is True
        assert obj.get("enhancements", {}).get("declared") == 8 and obj["enhancements"].get("integrity_ok") is True
        assert not obj.get("critical_failed"), obj.get("critical_failed")
        governance = obj.get("governance", {})
        assert governance.get("file_exists_is_not_sufficient_for_active") is True
        assert governance.get("critical_partial_blocks_unqualified_go") is True
        performance = obj.get("performance", {})
        assert performance.get("prediction_snapshot_reads") == 1
        assert performance.get("audit_scoped_cache") is True

    # PRE-FLIGHT is intentionally incomplete. Post-flight-only outputs must be DEFERRED,
    # never misclassified as failures.
    pre_counts = pre["gate0"]["counts"]
    assert pre_counts.get("PASS", 0) + pre_counts.get("DEFERRED", 0) == 16, pre_counts
    assert pre.get("governance", {}).get("preflight_defers_postflight_outputs") is True, pre

    # POST-FLIGHT is final-decision readiness. Nothing may remain deferred.
    post_counts = post["gate0"]["counts"]
    assert post_counts.get("PASS", 0) == 16 and post_counts.get("DEFERRED", 0) == 0, post_counts
    governance = post.get("governance", {})
    assert governance.get("health_check_must_precede_recommendation") is True
    assert governance.get("raw_optimizer_is_not_final_decision") is True
    assert governance.get("gate0_fail_blocks_go") is True

    # V4.7.1 distinguishes implemented evidence from inferred or fallback data.
    core = {row["id"]: row for row in post["dss_core"]["items"]}
    for module_id in ("DSS-05", "DSS-35"):
        assert core[module_id]["status"] == "ACTIVE", core[module_id]
    for module_id in ("DSS-09", "DSS-10", "DSS-11", "DSS-12", "DSS-13", "DSS-24"):
        assert core[module_id]["status"] == "PARTIAL", core[module_id]
    enhancements = {row["id"]: row for row in post["enhancements"]["items"]}
    assert enhancements["ENH-01"]["status"] == "PARTIAL", enhancements["ENH-01"]
    assert post.get("overall") == "AMBER", post.get("overall")
    assert post.get("go_allowed") is False, post

    return pre, post


def run() -> dict:
    pre, health = _assert_framework_health()

    latest = _load("latest.json")
    reliability = validate_snapshot(latest)
    assert reliability["ok"], reliability
    assert latest.get("schema_version", 0) >= 40
    assert int(latest.get("schema_version", 0)) >= 472
    assert str(latest.get("engine_version", "")).startswith("4.7.2-performance-hotfix")
    assert latest.get("meta", {}).get("parallel_fetch_is_single_snapshot_not_polling") is True

    compliance = _load("compliance_audit.json")
    assert compliance.get("overall") == "PASS", compliance

    predictions = _load("predictions_v4.json")
    players = predictions.get("players", [])
    coverage = predictions.get("input_coverage", {})
    assert int(predictions.get("schema_version", 0)) >= 471
    assert str(predictions.get("model_version", "")).startswith("v4.7.1-correctness-hotfix")
    assert predictions.get("point_in_time") is True and len(players) >= 500, predictions
    assert coverage.get("advanced_matched", 0) > 0 and coverage.get("last_season_matched", 0) > 0, coverage
    assert 0 <= coverage.get("advanced_materially_distinct", -1) <= coverage.get("advanced_matched", 0), coverage

    wc = _load("wc_decision_v4.json")
    assert int(wc.get("schema_version", 0)) >= 472, wc
    assert str(wc.get("engine", "")).startswith("v4.7.2-wc-optimizer-performance-hotfix"), wc
    assert wc.get("screened_players", 0) >= 500 and len(wc.get("optimized_elements", [])) == 15
    assert wc.get("classification") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    wp = wc.get("performance", {})
    assert wp.get("fast_finalist_scoring") and wp.get("winner_only_legality_check")
    assert wp.get("beam_size_unchanged") and wp.get("packed_club_signature") and wp.get("counter_copy_eliminated")
    assert wp.get("direct_challenger_position_index")
    assert wp.get("precomputed_club_bits") and wp.get("bounded_top_k_same_beam")
    wa = wc.get("affordability", {})
    assert wa.get("price_basis") == "owned_sell_cost_unowned_now_cost", wa
    assert wc.get("budget_tenths") == wa.get("available_budget_tenths"), wa

    packages = _load("wc_package_audit_v4.json")
    assert int(packages.get("schema_version", 0)) >= 472, packages
    assert str(packages.get("engine", "")).startswith("v4.7.2-wc-package-audit-performance-hotfix"), packages
    assert packages.get("max_replacements") == 4
    assert set(packages.get("best_by_replacement_count", {})) == {"1", "2", "3", "4"}
    assert packages.get("overall_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    assert packages.get("guardrails", {}).get("risk_penalty_enabled") is True
    assert packages.get("guardrails", {}).get("search_width_unchanged") is True
    pp = packages.get("performance", {})
    assert pp.get("metrics_cache_entries", 0) > 0
    assert pp.get("single_pass_metrics") and pp.get("compact_target_cache") and pp.get("score_only_hotloop")
    assert pp.get("redundant_target_validation_removed") and pp.get("candidate_reuse_supported")
    assert pp.get("packed_club_signature") and pp.get("top_packages_only_payload_materialization")
    pa = packages.get("affordability", {})
    assert pa.get("price_basis") == "owned_sell_cost_unowned_now_cost", pa
    assert packages.get("guardrails", {}).get("budget_tenths") == pa.get("available_budget_tenths"), pa

    lineup = _load("lineup_decision_v4.json")
    assert int(lineup.get("schema_version", 0)) >= 452, lineup
    assert str(lineup.get("engine", "")).startswith("v4.5.2-lineup-robust-governance"), lineup
    assert len(lineup.get("starting_xi", [])) == 11
    assert lineup.get("formation") in {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}
    xi_ids = {x["element"] for x in lineup["starting_xi"]}
    captain_id = lineup["captain"]["element"]
    vice_id = lineup["vice_captain"]["element"]
    assert captain_id in xi_ids and vice_id in xi_ids and captain_id != vice_id
    assert len(lineup.get("bench", {}).get("order", [])) == 3 and lineup.get("bench", {}).get("gk")
    assert lineup.get("chip_context", {}).get("single_chip_rule_respected") is True
    lg = lineup.get("guardrails", {})
    assert lg.get("captain_risk_adjusted") and lg.get("captain_safe_pool_preferred")
    assert lg.get("manual_draft_not_overwritten_without_margin") and lg.get("prediction_interval_robustness")
    assert lineup.get("governance", {}).get("decision") in {"OPTIMIZER_ONLY", "HOLD_MANUAL_DRAFT", "CHANGE_RECOMMENDED"}

    sanity = _load("recommendation_sanity_v4.json")
    assert int(sanity.get("schema_version", 0)) >= 460, sanity
    assert str(sanity.get("engine", "")).startswith("v4.6-evidence-fusion-sanity"), sanity
    assert sanity.get("point_in_time") is True
    assert sanity.get("final_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    sg = sanity.get("guardrails", {})
    assert sg.get("raw_optimizer_not_authoritative") and sg.get("rate_spike_detection")
    assert sg.get("team_cluster_penalty") and sg.get("outgoing_baseline_resistance")
    assert sg.get("early_season_multi_change_cap") and sg.get("point_in_time_required")

    pipeline = _load("decision_pipeline_v4.json")
    assert int(pipeline.get("schema_version", 0)) >= 472, pipeline
    assert str(pipeline.get("engine", "")).startswith("v4.7.2-unified-decision-pipeline-performance"), pipeline
    pg = pipeline.get("performance_guardrails", {})
    assert pg.get("shared_json_loaded_once") and pg.get("shared_candidates_built_once")
    assert pg.get("fork_copy_on_write") and pg.get("parallel_wc_package")
    assert pg.get("search_quality_reduction") is False
    assert pg.get("wc_beam_unchanged") and pg.get("package_frontier_beam_unchanged")
    assert pg.get("bounded_top_k_same_wc_beam") and pg.get("top_packages_only_payload_materialization")
    timings = pipeline.get("timings", {})
    assert timings.get("total_pipeline_ms", 0) > 0

    all_x: list[float] = []
    strong_direct_evidence: list[float] = []
    no_direct_evidence: list[float] = []
    for row in players:
        assert len(row.get("fixtures", [])) <= 15 and row.get("xpts_5", 0) >= 0
        for fx in row.get("fixtures", []):
            x = fx["xpts"]
            all_x.append(x)
            assert 0 <= x < 25
            assert fx["components"].get("defcon", 0) <= 2.001
            if row.get("position") == "GK":
                assert fx["components"].get("defcon", 0) == 0
            assert fx["lower80"] <= x <= fx["upper80"]
            calibration = fx.get("calibration", {})
            provenance = fx.get("provenance", {})
            for field in ("nailed_prior", "current_start_rate", "current_minutes_rate", "competition_pressure", "set_piece_order_weight", "penalty_order_weight", "last_season_weight", "opponent_defence_resistance"):
                assert field in calibration, (row.get("element"), field)
            assert provenance.get("xmins_prior_source")
            assert provenance.get("set_piece_source") == "official_fpl_bootstrap_orders_inferred_metadata"
            assert provenance.get("role_scoring_mode") == "metadata_only_no_double_count"
            assert fx["components"].get("set_piece_penalty_adjustment") == 0
            assert str(provenance.get("opponent_defence_source", "")).startswith("official_fpl_")
            xm = fx["xmins"]
            assert abs(xm["start_probability"] + xm["bench_probability"] + xm["dnp_probability"] - 1) < 0.002
        if row.get("fixtures"):
            calibration = row["fixtures"][0]["calibration"]
            xm = row["fixtures"][0]["xmins"]
            priors = row.get("priors") or {}
            if xm.get("availability_probability", 0) >= .99 and calibration.get("nailed_prior", 0) >= .8 and calibration.get("current_start_rate", 0) >= .8:
                strong_direct_evidence.append(xm["start_probability"])
            if (
                xm.get("availability_probability", 0) >= .99
                and not priors.get("prior_season_available")
                and calibration.get("current_start_rate", 0) == 0
                and calibration.get("current_minutes_rate", 0) == 0
            ):
                no_direct_evidence.append(xm["expected_minutes"])
    assert strong_direct_evidence and min(strong_direct_evidence) >= .75, strong_direct_evidence
    assert no_direct_evidence and max(no_direct_evidence) <= 22, no_direct_evidence
    assert all_x and statistics.median(all_x) < 8
    assert sum(x > 15 for x in all_x) / len(all_x) < 0.03

    out = {
        "health": health["overall"],
        "preflight_gate0": pre["gate0"]["counts"],
        "postflight_gate0": health["gate0"]["counts"],
        "dss50": health["dss_core"]["counts"],
        "extensions": health["dss_extensions"]["counts"],
        "enhancements": health["enhancements"]["counts"],
        "recommendation": sanity["final_verdict"],
        "lineup_governance": lineup["governance"]["decision"],
        "formation": lineup["formation"],
        "captain": lineup["captain"]["name"],
        "pipeline_ms": timings["total_pipeline_ms"],
    }
    print("V4.7.2 PERFORMANCE + DECISION-EQUIVALENCE QUALITY GATE PASS", json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
