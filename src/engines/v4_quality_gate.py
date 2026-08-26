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
        assert int(obj.get("schema_version", 0)) >= 4602, obj
        assert str(obj.get("engine", "")).startswith("v4.6.3-framework-health-auditor"), obj
        assert obj.get("phase") == phase, obj
        assert obj.get("registry_integrity") is True, obj
        assert obj.get("overall") in {"GREEN", "AMBER"}, obj
        assert obj.get("go_allowed") is True, obj
        assert obj.get("gate0", {}).get("pass") is True, obj.get("gate0")
        assert obj.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0, obj.get("gate0")
        assert obj.get("dss_core", {}).get("declared") == 50 and obj["dss_core"].get("integrity_ok") is True
        assert obj.get("dss_extensions", {}).get("declared") == 16 and obj["dss_extensions"].get("integrity_ok") is True
        assert obj.get("enhancements", {}).get("declared") == 8 and obj["enhancements"].get("integrity_ok") is True
        assert not obj.get("critical_failed"), obj.get("critical_failed")

    # PRE-FLIGHT is intentionally incomplete. Post-flight-only outputs must be DEFERRED,
    # never misclassified as failures.
    pre_counts = pre["gate0"]["counts"]
    assert pre_counts.get("PASS", 0) + pre_counts.get("DEFERRED", 0) == 16, pre_counts
    assert pre.get("reporting_contract", {}).get("preflight_defers_postflight_outputs") is True, pre

    # POST-FLIGHT is final-decision readiness. Nothing may remain deferred.
    post_counts = post["gate0"]["counts"]
    assert post_counts.get("PASS", 0) == 16 and post_counts.get("DEFERRED", 0) == 0, post_counts
    rc = post.get("reporting_contract", {})
    assert rc.get("health_check_first") is True
    assert rc.get("raw_optimizer_distinct_from_governed_recommendation") is True
    assert rc.get("manual_draft_distinct_from_final_lock") is True
    assert rc.get("gate0_fail_blocks_go") is True

    return pre, post


def run() -> dict:
    pre, health = _assert_framework_health()

    latest = _load("latest.json")
    reliability = validate_snapshot(latest)
    assert reliability["ok"], reliability
    assert latest.get("schema_version", 0) >= 40
    assert str(latest.get("engine_version", "")).startswith("4.0")

    compliance = _load("compliance_audit.json")
    assert compliance.get("overall") == "PASS", compliance

    predictions = _load("predictions_v4.json")
    players = predictions.get("players", [])
    assert predictions.get("point_in_time") is True and len(players) >= 500, predictions

    wc = _load("wc_decision_v4.json")
    assert int(wc.get("schema_version", 0)) >= 447, wc
    assert str(wc.get("engine", "")).startswith("v4.4.6-wc-optimizer-packed-clubs"), wc
    assert wc.get("screened_players", 0) >= 500 and len(wc.get("optimized_elements", [])) == 15
    assert wc.get("classification") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    wp = wc.get("performance", {})
    assert wp.get("fast_finalist_scoring") and wp.get("winner_only_legality_check")
    assert wp.get("beam_size_unchanged") and wp.get("packed_club_signature") and wp.get("counter_copy_eliminated")
    assert wp.get("direct_challenger_position_index")

    packages = _load("wc_package_audit_v4.json")
    assert int(packages.get("schema_version", 0)) >= 447, packages
    assert str(packages.get("engine", "")).startswith("v4.4.6-wc-package-audit"), packages
    assert packages.get("max_replacements") == 4
    assert set(packages.get("best_by_replacement_count", {})) == {"1", "2", "3", "4"}
    assert packages.get("overall_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    assert packages.get("guardrails", {}).get("risk_penalty_enabled") is True
    assert packages.get("guardrails", {}).get("search_width_unchanged") is True
    pp = packages.get("performance", {})
    assert pp.get("metrics_cache_entries", 0) > 0
    assert pp.get("single_pass_metrics") and pp.get("compact_target_cache") and pp.get("score_only_hotloop")
    assert pp.get("redundant_target_validation_removed") and pp.get("candidate_reuse_supported")

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
    assert int(pipeline.get("schema_version", 0)) >= 461, pipeline
    assert str(pipeline.get("engine", "")).startswith("v4.6.1-unified-decision-pipeline-fast-parallel"), pipeline
    pg = pipeline.get("performance_guardrails", {})
    assert pg.get("shared_json_loaded_once") and pg.get("shared_candidates_built_once")
    assert pg.get("fork_copy_on_write") and pg.get("parallel_wc_package")
    assert pg.get("search_quality_reduction") is False
    assert pg.get("wc_beam_unchanged") and pg.get("package_frontier_beam_unchanged")
    timings = pipeline.get("timings", {})
    assert timings.get("total_pipeline_ms", 0) > 0

    all_x: list[float] = []
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
            xm = fx["xmins"]
            assert abs(xm["start_probability"] + xm["bench_probability"] + xm["dnp_probability"] - 1) < 0.002
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
    print("V4.6.3 FRAMEWORK HEALTH + QUALITY GATE PASS", json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
