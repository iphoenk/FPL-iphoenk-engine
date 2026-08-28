from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.engines import owned_challenger_comparator as comparator
from src.engines import owned_challenger_transfer_context as transfer_context
from src.engines import report_comparator_overlay

ROOT = Path(__file__).resolve().parents[1]


def _proj(
    element: int,
    name: str,
    position: str = "MID",
    *,
    team_id: int = 1,
    cost: int = 60,
    gw_mean: float = 3.0,
    gw_std: float = 1.0,
    start: float = 0.75,
    dnp: float = 0.08,
    minutes: float = 72.0,
    confidence: str = "MEDIUM",
    status: str = "a",
    xg90: float = 0.12,
    xa90: float = 0.12,
    tactical_state: str = "READY",
) -> dict:
    rows = []
    for idx in range(5):
        rows.append({
            "gw": 2 + idx,
            "mean": gw_mean,
            "std": gw_std,
            "fixtures": [{
                "event": 2 + idx,
                "kickoff_time": f"2026-09-{1 + idx:02d}T15:00:00Z",
                "opponent": 20 if team_id != 20 else 19,
                "home": idx % 2 == 0,
                "mean": gw_mean,
                "std": gw_std,
            }],
        })
    return {
        "element": element,
        "name": name,
        "team_id": team_id,
        "team": f"Team {team_id}",
        "position": position,
        "element_type": {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position],
        "now_cost": cost,
        "status": status,
        "projection_confidence": confidence,
        "current_season": {"starts": 1, "minutes": 90},
        "xmins": {
            "expected_minutes": minutes,
            "start_probability": start,
            "bench_probability": max(0.0, 1.0 - start - dnp),
            "dnp_probability": dnp,
        },
        "rates": {"xg90": xg90, "xa90": xa90, "bonus90": 0.2, "dc90": 0.0, "saves90": 0.0},
        "xpts_by_gw": rows,
        "tactical_role": {"profile": "ADVANCED_RUNNER", "confidence": "MEDIUM", "decision_influence": "ADVISORY_ONLY"},
        "tactical_matchup": {
            "evidence_state": tactical_state,
            "decision_usage": "ADVISORY_ONLY",
            "highlights": ["observed matchup edge"] if tactical_state == "READY" else [],
        },
    }


def _owned(proj: dict, *, sell_cost: int | None = None) -> dict:
    return {
        "element": proj["element"],
        "name": proj["name"],
        "team_id": proj["team_id"],
        "team": proj["team"],
        "position": proj["position"],
        "now_cost": proj["now_cost"],
        "sell_cost": proj["now_cost"] if sell_cost is None else sell_cost,
        "projection": proj,
    }


def _comparison(
    out_proj: dict,
    in_proj: dict,
    *,
    challenger_type: str = "GOVERNED_WATCHLIST",
    performance_signal: str = "GOVERNED_WATCHLIST",
    itb: int = 0,
    package: dict | None = None,
    owned_all: list[dict] | None = None,
) -> dict:
    out = _owned(out_proj)
    owned_all = owned_all or [out]
    packages = {in_proj["element"]: package} if package else {}
    return comparator._comparison(
        out,
        in_proj,
        challenger_type,
        performance_signal,
        [],
        {"passed": True},
        owned_all,
        itb,
        packages,
        {},
        {out_proj["team_id"]: out_proj["team"], in_proj["team_id"]: in_proj["team"], 20: "Opponent"},
        [{"rank": 1, "element": out_proj["element"], "name": out_proj["name"]}],
    )


def test_generic_source_has_no_named_player_pair_and_no_duplicate_model_imports():
    text = inspect.getsource(comparator)
    assert "Rogers" not in text
    assert "Cherki" not in text
    assert "historical_projection import" not in text
    assert "team_strength import" not in text
    assert "tactical_matchup import" not in text
    assert "price_radar import" not in text
    assert "package_optimizer_v2 import" not in text


def test_policy_is_advisory_only_and_explicitly_reuses_canonical_engines():
    policy = comparator.load_policy()
    assert policy["contract"] == "OWNED_CHALLENGER_COMPARATOR_V1"
    assert policy["capability_status"] == "ADVISORY_ONLY"
    governance = policy["governance"]
    assert governance["reuse_canonical_projection_xpts"] is True
    assert governance["reuse_canonical_xmins"] is True
    assert governance["reuse_canonical_tactical_matchup"] is True
    assert governance["reuse_canonical_package_legality_and_scoring"] is True
    assert governance["reuse_canonical_price_state"] is True
    assert governance["may_not_overwrite_canonical_transfer_recommendation"] is True


def test_horizon_1_2_3_5_is_sum_of_canonical_xpts_by_gw_only():
    proj = _proj(1, "Owned", gw_mean=2.5, gw_std=1.2)
    assert comparator._horizon(proj, 1) == (2.5, 1.2)
    assert comparator._horizon(proj, 2)[0] == 5.0
    assert comparator._horizon(proj, 3)[0] == 7.5
    assert comparator._horizon(proj, 5)[0] == 12.5


def test_single_haul_is_discovery_signal_not_sustainable_candidate():
    proj = _proj(50, "Haul Trigger", gw_mean=3.0, xg90=0.05, xa90=0.05)
    signal, triggers, screen = comparator._emerging_signal(proj, {"goals": 2, "assists": 0, "xg": 0.1, "xa": 0.0, "shots": 1, "box_touches": 2, "chances_created": 0})
    assert "MULTIPLE_MATCH_RETURNS" in triggers
    assert screen["passed"] is True
    assert signal == "INTERESTING"


def test_strong_process_plus_secure_role_can_be_sustainable_candidate():
    proj = _proj(51, "Process Trigger", gw_mean=4.0, xg90=0.35, xa90=0.20, start=0.82)
    signal, triggers, screen = comparator._emerging_signal(proj, {"goals": 1, "assists": 1, "xg": 0.9, "xa": 0.4, "shots": 5, "box_touches": 10, "chances_created": 5})
    assert screen["passed"] is True
    assert len(triggers) >= 2
    assert signal == "SUSTAINABLE_CANDIDATE"


def test_injury_or_suspension_fails_emerging_eligibility():
    for status in ("i", "s"):
        proj = _proj(52, "Unavailable", status=status, gw_mean=4.0, start=0.8, xg90=0.4, xa90=0.2)
        signal, _, screen = comparator._emerging_signal(proj, {"xg": 1.0, "shots": 5, "box_touches": 10})
        assert screen["passed"] is False
        assert signal != "SUSTAINABLE_CANDIDATE"


def test_improving_and_deteriorating_xmins_are_screened_not_assumed():
    strong = _proj(53, "Secure", start=0.82, minutes=78, dnp=0.04, gw_mean=4.0, xg90=0.4)
    weak = _proj(54, "Risky", start=0.30, minutes=35, dnp=0.45, gw_mean=4.0, xg90=0.4)
    assert comparator._emerging_signal(strong, {"xg": 0.9, "shots": 5})[2]["passed"] is True
    assert comparator._emerging_signal(weak, {"xg": 0.9, "shots": 5})[2]["passed"] is False


def test_owned_target_selection_is_same_position_and_not_blind_cartesian_product():
    mid1 = _owned(_proj(1, "Mid One", "MID", gw_mean=2.0, start=0.55))
    mid2 = _owned(_proj(2, "Mid Two", "MID", gw_mean=3.0, start=0.75))
    mid3 = _owned(_proj(3, "Mid Three", "MID", gw_mean=4.0, start=0.90))
    defender = _owned(_proj(4, "Defender", "DEF", gw_mean=1.0))
    incoming = _proj(20, "Mid Challenger", "MID", cost=65, gw_mean=4.5)
    targets = comparator._target_outs(incoming, [mid1, mid2, mid3, defender], {2, 3}, 5)
    assert len(targets) == 3
    assert all(row["position"] == "MID" for row in targets)
    assert all(row["element"] != defender["element"] for row in targets)
    assert targets[0]["element"] == 1


def test_same_price_direct_swap_is_affordable():
    out = _proj(1, "Owned", cost=60, gw_mean=3.0)
    incoming = _proj(2, "Incoming", cost=60, gw_mean=4.0)
    result = _comparison(out, incoming)
    assert result["affordability"] is True
    assert result["structural_cost"]["direct_swap_affordable"] is True


def test_upgrade_requires_itb_and_downgrade_is_affordable():
    out = _owned(_proj(1, "Owned", cost=60), sell_cost=60)
    upgrade = _proj(2, "Upgrade", cost=65)
    targets_without_itb = comparator._target_outs(upgrade, [out], set(), 0)
    targets_with_itb = comparator._target_outs(upgrade, [out], set(), 5)
    assert targets_without_itb[0]["direct_affordable"] is False
    assert targets_with_itb[0]["direct_affordable"] is True
    downgrade = _proj(3, "Downgrade", cost=55)
    assert comparator._target_outs(downgrade, [out], set(), 0)[0]["direct_affordable"] is True


def test_club_limit_violation_is_detected_before_transfer_label():
    out_proj = _proj(1, "Out", team_id=1)
    owned = [_owned(out_proj)] + [_owned(_proj(10 + i, f"Other {i}", position="DEF", team_id=2 if i < 3 else 3)) for i in range(4)]
    incoming = _proj(99, "Fourth Club Two", team_id=2)
    legal, counts = comparator._club_legal(owned, owned[0], incoming)
    assert counts["2"] == 4
    assert legal is False


def test_position_legality_is_preserved_by_target_selector():
    owned = [_owned(_proj(1, "GK", "GK")), _owned(_proj(2, "DEF", "DEF")), _owned(_proj(3, "MID", "MID")), _owned(_proj(4, "FWD", "FWD"))]
    incoming = _proj(99, "Incoming Defender", "DEF")
    targets = comparator._target_outs(incoming, owned, set(), 100)
    assert [row["position"] for row in targets] == ["DEF"]


def test_missing_current_tactical_evidence_does_not_become_positive_edge():
    proj = _proj(2, "Incoming", tactical_state="PARTIAL")
    assert comparator._tactical_for_gw(proj, 0)["evidence_state"] == "PARTIAL"
    assert comparator._tactical_for_gw(proj, 1)["evidence_state"] == "UNVERIFIED"


def test_tbd_future_fixture_is_explicit_not_fabricated():
    proj = _proj(2, "Incoming")
    proj["xpts_by_gw"][1]["fixtures"][0]["opponent"] = 999
    context = comparator._fixture_context(proj, 1, {})
    assert context["fixtures"][0]["opponent"] is None
    assert context["fixtures"][0]["opponent_team_id"] == 999


def test_europe_domestic_cup_and_international_are_pending_when_not_verified():
    result = _comparison(_proj(1, "Owned", gw_mean=3.0), _proj(2, "Incoming", gw_mean=4.0))
    assert result["midweek_schedule"]["state"] == "PENDING_REPORT_TIME"
    assert result["international_context"]["state"] == "PENDING_REPORT_TIME"
    assert all(row["challenger"]["rest_congestion"]["cross_competition_load"] == "PENDING_REPORT_TIME" for row in result["fixture_by_fixture"])


def test_missing_external_source_is_pending_and_majority_vote_forbidden():
    result = _comparison(_proj(1, "Owned", gw_mean=3.0), _proj(2, "Incoming", gw_mean=4.0))
    consensus = result["external_model_consensus"]
    assert consensus["state"] == "PENDING_REPORT_TIME"
    assert consensus["majority_vote_forbidden"] is True
    assert "DIVERGE" in consensus["allowed_states"]


def test_emerging_non_sustainable_candidate_cannot_become_transfer_even_with_large_edge():
    result = _comparison(
        _proj(1, "Owned", gw_mean=1.0),
        _proj(2, "Incoming", gw_mean=6.0, start=0.9),
        challenger_type="EMERGING_CHALLENGER",
        performance_signal="INTERESTING",
    )
    assert result["decision"] == "WATCH_CHALLENGER"


def test_positive_edge_smaller_than_uncertainty_stays_review_not_auto_transfer():
    out = _proj(1, "Owned", gw_mean=3.0, gw_std=3.0)
    incoming = _proj(2, "Incoming", gw_mean=3.7, gw_std=3.0, start=0.8)
    result = _comparison(out, incoming)
    assert result["raw_gain_5gw"] > 0
    assert result["signal_to_noise_5gw"] < 0.55
    assert result["decision"] in {"HOLD_OWNED", "REVIEW"}


def test_large_secure_edge_with_canonical_package_is_only_lean_while_advisory():
    out = _proj(1, "Owned", gw_mean=2.0, gw_std=0.5)
    incoming = _proj(2, "Incoming", gw_mean=5.0, gw_std=0.5, start=0.9)
    package = {"package_id": "P1", "robust_gain_vs_hold": 6.2, "resulting_itb": 0, "changes": 1, "legal": True}
    result = _comparison(out, incoming, package=package)
    assert result["raw_gain_5gw"] >= 5
    assert result["decision"] == "LEAN_TRANSFER"
    assert result["advisory_only"] is True


def test_early_season_low_confidence_caps_comparison_confidence():
    result = _comparison(_proj(1, "Owned", confidence="LOW"), _proj(2, "Incoming", confidence="MEDIUM", gw_mean=4.0))
    assert result["confidence"] == "LOW"


def test_comparison_exposes_fixture_by_fixture_required_semantics():
    result = _comparison(_proj(1, "Owned", gw_mean=3.0), _proj(2, "Incoming", gw_mean=4.0))
    assert len(result["fixture_by_fixture"]) == 5
    for key in ("horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw", "xpts_by_gw", "xmins_by_gw", "start_probability_by_gw", "tactical_matchup_by_gw", "rest_congestion_by_gw", "role_sustainability", "reversal_triggers"):
        assert key in result


def test_reversal_triggers_cover_role_injury_workload_fixture_price_and_regression():
    result = _comparison(_proj(1, "Owned"), _proj(2, "Incoming", gw_mean=4.0))
    text = " ".join(result["reversal_triggers"]).lower()
    for token in ("xmins", "competitor", "injury", "international", "fixture", "price", "regresses"):
        assert token in text


def test_active_wildcard_removes_normal_ft_and_hit_costs():
    team = {"projection_baseline": {"override_applied": True, "override_kind": "WILDCARD", "override_target_gw": 2, "effective_authority": "LOCKED_PRE_DEADLINE", "authority_source": "USER_LOCK"}}
    chip = transfer_context._active_planning_chip(team)
    opportunity = transfer_context._opportunity_cost(chip)
    assert chip["chip"] == "WILDCARD"
    assert opportunity["free_transfer_cost_applied"] is False
    assert opportunity["hit_cost_applied"] is False


def test_normal_transfer_state_does_not_fabricate_ft_or_hit_cost():
    chip = transfer_context._active_planning_chip({"projection_baseline": {"override_applied": False}})
    opportunity = transfer_context._opportunity_cost(chip)
    assert opportunity["state"] == "PENDING_VERIFIED_TRANSFER_STATE"
    assert opportunity["free_transfer_cost_applied"] is None
    assert opportunity["hit_cost_applied"] is None


def test_free_hit_caps_permanent_transfer_actionability():
    chip = transfer_context._active_planning_chip({"projection_baseline": {"override_applied": True, "override_kind": "FREE_HIT", "override_target_gw": 2}})
    assert transfer_context._opportunity_cost(chip)["state"] == "FREE_HIT_ACTIVE"


def test_watchlist_promotion_and_demotion_are_not_mutated_by_advisory_comparator():
    policy = comparator.load_policy()["governance"]
    assert policy["may_not_overwrite_watchlist"] is True
    assert policy["one_match_haul_is_trigger_not_buy"] is True


def test_service_wiring_adds_no_new_microservice_and_uses_watchlist_bounded_context():
    base = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())
    commands = [row["module"] for row in base["services"]["watchlist"]["commands"]]
    assert "src.engines.owned_challenger_comparator" in commands
    assert "src.engines.owned_challenger_transfer_context" in commands
    assert "owned_challenger_comparator" not in base["services"]
    report_commands = [row["module"] for row in base["services"]["report_materializer"]["commands"]]
    assert "src.engines.report_comparator_overlay" in report_commands


def test_architecture_registry_has_one_comparator_owner_and_no_formula_ownership():
    registry = json.loads((ROOT / "config" / "v3_architecture_ownership_registry.json").read_text())
    rows = [row for row in registry["responsibilities"] if row["id"] == "OWNED_CHALLENGER_COMPARISON"]
    assert len(rows) == 1
    assert rows[0]["owner_service"] == "watchlist"
    assert registry["policy"]["owned_challenger_comparison_may_not_duplicate_projection_xmins_fixture_tactical_price_or_package_engines"] is True


def test_rec43_official_first_and_implementation_status_are_synchronized():
    rec = json.loads((ROOT / "config" / "rec_registry.json").read_text())
    official = json.loads((ROOT / "config" / "sources" / "official_first_coverage.json").read_text())
    implementation = json.loads((ROOT / "IMPLEMENTATION_STATUS.json").read_text())
    rec43 = next(row for row in rec["records"] if row["id"] == "REC-43")
    assert rec43["status"] == "CANDIDATE"
    assert rec43["owner"] == "watchlist"
    assert official["recommendations"]["REC-43"]["applicability"] == "PUBLIC_FIRST_WITH_ENRICHMENT"
    assert implementation["rec_status"]["REC-43"]["status"] == "CANDIDATE"
    assert set(row["id"] for row in rec["records"]) == set(official["recommendations"]) == set(implementation["rec_status"])


def test_artifact_contract_and_publication_path_are_declared():
    contracts = json.loads((ROOT / "config" / "runtime" / "artifact_contracts.json").read_text())
    publish = json.loads((ROOT / "config" / "runtime" / "runtime_publish_registry.json").read_text())
    spec = contracts["contracts"]["owned_challenger_comparator.json"]
    assert spec["equals"]["contract"] == "OWNED_CHALLENGER_COMPARATOR_V1"
    assert spec["equals"]["capability_status"] == "ADVISORY_ONLY"
    assert "owned_challenger_comparator.json" in publish["publish_paths"]


def test_report_overlay_is_additive_and_does_not_replace_canonical_decision(tmp_path, monkeypatch):
    comparator_payload = {
        "contract": "OWNED_CHALLENGER_COMPARATOR_V1",
        "capability_status": "ADVISORY_ONLY",
        "planning_gw": 2,
        "challenger_counts": {"governed_watchlist": 1, "emerging": 1, "comparisons": 1},
        "top_comparisons": [{
            "player_out": {"element": 1, "name": "Owned", "position": "MID", "price": 6.0},
            "player_in": {"element": 2, "name": "Incoming", "position": "MID", "price": 6.0},
            "challenger_type": "GOVERNED_WATCHLIST",
            "performance_signal": "GOVERNED_WATCHLIST",
            "raw_gain_2gw": 1.0,
            "raw_gain_3gw": 2.0,
            "raw_gain_5gw": 3.0,
            "decision": "REVIEW",
            "confidence": "MEDIUM",
            "decision_reasons": ["reason"],
            "decision_risks": ["risk"],
            "reversal_triggers": ["trigger"],
        }],
        "emerging_challengers": [],
        "common_output_semantics": [],
        "governance": {},
    }
    paths = {
        "COMPARATOR": tmp_path / "owned_challenger_comparator.json",
        "USER": tmp_path / "user_report.json",
        "BRIEF": tmp_path / "decision_brief.json",
        "DEEP": tmp_path / "deep_review_payload.json",
    }
    paths["COMPARATOR"].write_text(json.dumps(comparator_payload))
    for key in ("USER", "BRIEF", "DEEP"):
        paths[key].write_text(json.dumps({"decision": "HOLD", "captain": "Existing Captain"}))
        monkeypatch.setattr(report_comparator_overlay, key, paths[key])
    monkeypatch.setattr(report_comparator_overlay, "COMPARATOR", paths["COMPARATOR"])
    result = report_comparator_overlay.run()
    assert result["status"] == "PASS"
    for key in ("USER", "BRIEF", "DEEP"):
        payload = json.loads(paths[key].read_text())
        assert payload["decision"] == "HOLD"
        assert payload["captain"] == "Existing Captain"
        assert payload["owned_vs_challenger"]["advisory_only"] is True


def test_dynamic_acceptance_selects_owned_governed_watchlist_and_emerging_challenger(tmp_path, monkeypatch):
    projections = []
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    ledger = []
    for idx, position in enumerate(positions, start=1):
        proj = _proj(idx, f"Owned {idx}", position, team_id=(idx % 8) + 1, cost=55 + (idx % 4) * 5, gw_mean=2.6 + (idx % 3) * 0.2, xg90=0.05, xa90=0.05)
        projections.append(proj)
        ledger.append({"element": idx, "name": proj["name"], "position": position, "now_cost": proj["now_cost"], "sell_cost": proj["now_cost"]})

    governed = _proj(101, "Governed Candidate", "MID", team_id=10, cost=60, gw_mean=4.0, start=0.82, xg90=0.35, xa90=0.18)
    emerging = _proj(102, "Emerging Candidate", "MID", team_id=11, cost=60, gw_mean=4.2, start=0.84, xg90=0.40, xa90=0.20)
    projections.extend([governed, emerging])

    data = tmp_path
    (data / "stats").mkdir()
    (data / "projections.json").write_text(json.dumps({"planning_gw": 2, "players": projections}))
    (data / "team.json").write_text(json.dumps({"team_value_ledger": ledger, "totals": {"itb": 5}}))
    (data / "dss_watchlist.json").write_text(json.dumps({"status": "READY", "positions": {"GK": [], "DEF": [], "MID": [{"element": 101}], "FWD": []}}))
    (data / "universe.json").write_text(json.dumps({"players": []}))
    (data / "package_optimizer.json").write_text(json.dumps({"hold": {"score": {"robust_score": 100}}, "packages": []}))
    (data / "lineup_decision.json").write_text(json.dumps({"selected_xi": list(range(1, 12))}))
    (data / "official_detail.json").write_text(json.dumps({"element_summaries": {}}))
    (data / "stats" / "playermatchstats_current.json").write_text(json.dumps({"rows": [{
        "player_id": "102", "minutes_played": "90", "goals": "1", "assists": "1", "xg": "0.9", "xa": "0.4", "total_shots": "5", "touches_opposition_box": "10", "chances_created": "5", "penalties_scored": "0"
    }]}))

    monkeypatch.setattr(comparator, "DATA", data)
    monkeypatch.setattr(comparator, "OUT", data / "owned_challenger_comparator.json")
    result = comparator.build()
    assert result["owned_count"] == 15
    assert result["challenger_counts"]["governed_watchlist"] == 1
    assert result["challenger_counts"]["emerging"] >= 1
    types = {row["challenger_type"] for row in result["comparisons"]}
    assert "GOVERNED_WATCHLIST" in types
    assert "EMERGING_CHALLENGER" in types
    assert any(row["performance_signal"] == "SUSTAINABLE_CANDIDATE" for row in result["emerging_challengers"])
    assert all(len(row["candidate_out_rank"]) <= 3 for row in result["comparisons"])
    assert all(row["advisory_only"] is True for row in result["comparisons"])
    assert {"horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw"} <= set(result["comparisons"][0])


@pytest.mark.parametrize(
    "scenario",
    [
        "same_price_direct_swap",
        "upgrade_requiring_itb",
        "downgrade",
        "active_wildcard",
        "normal_free_transfer",
        "european_congestion",
        "domestic_cup_congestion",
        "international_duty",
        "missing_tactical_data",
        "missing_external_source",
        "tbd_cup_or_european_opponent",
        "injury",
        "suspension",
        "one_match_haul",
        "haul_with_weak_underlying",
        "improving_xmins",
        "deteriorating_xmins",
        "same_club_limit_violation",
        "position_legality",
        "early_season_low_confidence",
        "watchlist_promotion",
        "watchlist_demotion",
        "multiple_challengers_one_owned",
        "one_challenger_multiple_owned",
        "cross_engine_divergence",
    ],
)
def test_all_spec_acceptance_scenarios_have_explicit_safe_governance(scenario):
    """The 25 specification scenarios must never fall through to an ungoverned strong action."""
    policy = comparator.load_policy()
    assert policy["capability_status"] == "ADVISORY_ONLY", scenario
    assert policy["governance"]["missing_evidence_is_explicit"] is True, scenario
    assert policy["governance"]["may_not_overwrite_canonical_transfer_recommendation"] is True, scenario
    assert policy["governance"]["may_not_overwrite_watchlist"] is True, scenario
    assert policy["governance"]["one_match_haul_is_trigger_not_buy"] is True, scenario
