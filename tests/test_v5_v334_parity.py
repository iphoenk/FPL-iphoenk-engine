from __future__ import annotations

from datetime import datetime, timezone

from src.v5.evaluation.decision_validation import capture, decision_regret
from src.v5.evaluation.external_consensus import normalize
from src.v5.intelligence.competitive_load import build_competitive_load
from src.v5.intelligence.tactical_matchup import attach_tactical_matchups


def test_external_consensus_is_advisory_fail_neutral_and_no_majority_vote():
    result = normalize({"observations":[
        {"source":"fffix","availability":"AVAILABLE","subject":"captain","normalized_direction":"SUPPORT_NATIVE","signal":"same captain"},
        {"source":"ffhub","availability":"AVAILABLE","subject":"captain","normalized_direction":"OPPOSE_NATIVE","signal":"different captain"},
        {"source":"unknown","availability":"AVAILABLE","subject":"captain","normalized_direction":"SUPPORT_NATIVE"},
    ]}, {"captain":411})
    assert result["overall"] == "REVIEW_DIVERGENCE"
    assert result["native_conclusion_frozen_before_overlay"] is True
    assert result["governance"]["majority_vote_used"] is False
    assert result["governance"]["native_truth_mutated"] is False
    assert result["source_status"]["livefpl"] == "UNAVAILABLE"
    assert all(row["source"] != "unknown" for row in result["observations"])


def test_competitive_load_uses_verified_evidence_and_never_invents_non_pl_context():
    bootstrap={"elements":[{"id":1,"team":1},{"id":2,"team":1}]}
    fixtures=[
        {"event":2,"team_h":1,"team_a":2,"kickoff_time":"2026-08-28T17:30:00Z"},
        {"event":3,"team_h":3,"team_a":1,"kickoff_time":"2026-09-04T17:30:00Z"},
    ]
    stats={"rows":[{"player_id":1,"minutes_played":90}]}
    observations={"contract":"COMPETITIVE_LOAD_OBSERVATIONS_V1","observations":[
        {
            "element":1,
            "verified":True,
            "verification_level":"OFFICIAL_NATIONAL_TEAM",
            "source":"official national team match centre",
            "source_url":"https://example.com/international/match-1",
            "competition":"International",
            "match_time":"2026-09-02T18:00:00Z",
            "started":True,
            "minutes":90,
            "extra_time_minutes":0,
            "international":True,
            "long_haul":True,
            "travel_context":"LONG_HAUL_AWAY"
        },
        {"element":2,"verified":False,"competition":"International","match_time":"2026-09-02T18:00:00Z","minutes":90,"international":True},
    ]}
    result=build_competitive_load(bootstrap,fixtures,planning_gw=3,match_stats=stats,verified_observations=observations,now=datetime(2026,9,3,0,0,tzinfo=timezone.utc))
    one=result["players"]["1"]; two=result["players"]["2"]
    assert one["verified_non_pl_observation_count"] == 1
    assert one["international_evidence"] is True
    assert one["long_haul_evidence"] is True
    assert one["travel_context"] == "LONG_HAUL_AWAY"
    assert one["state"] in {"CONGESTED","HIGH_ROTATION_RISK"}
    assert two["verified_non_pl_observation_count"] == 0
    assert two["non_pl_evidence_state"] == "UNAVAILABLE"
    assert result["observation_audit"]["accepted_rows"] == 1
    assert result["observation_audit"]["rejection_reasons"]["NOT_VERIFIED"] == 1
    assert result["governance"]["direct_xpts_mutation_forbidden"] is True
    assert result["governance"]["direct_xmins_mutation_forbidden_until_calibrated"] is True


def test_tactical_dimension_matrix_and_system_fit_are_explicit_not_fabricated():
    predictions={"players":[{"element":1,"team_id":1,"position":"MID","role":{"role":"CREATOR_PROFILE","return_routes":["box_pressure"]},"xpts_by_gw":[{"gw":3,"fixtures":[{"opponent":2,"home":False}]}]}]}
    context={"team_profiles":{"1":{"team_id":1,"base_formation":"4-3-3","coach":None,"evidence_class":"OBSERVED_FPL_POSITION_SHAPE"},"2":{"team_id":2,"base_formation":"4-4-2","coach":None,"vulnerabilities":["box_pressure"],"observed_style_proxies":["set_piece_activity"],"confidence":"LOW"}},"recent_form":{"2":[{"gw":2,"confidence":"LOW"}]}}
    result=attach_tactical_matchups(predictions,3,context)
    tactical=result["players"][0]["tactical_matchup"]
    assert tactical["tactical_matchup_label"] == "POSITIVE_EDGE"
    assert tactical["system_formation_fit"]["true_tactical_formation"] is None
    assert tactical["system_formation_fit"]["fit_score"] is None
    assert tactical["evidence_dimensions"]["opponent_coach"] == "UNAVAILABLE"
    assert tactical["evidence_dimensions"]["formation_or_variants"] == "PARTIAL"
    assert tactical["xpts_mutated"] is False
    assert tactical["xmins_mutated"] is False


def test_decision_snapshot_is_genuine_predeadline_frozen_and_regret_never_invents_hit_cost():
    context={"phase":"PRE_DEADLINE","planning_gw":3,"deadline_time":"2026-09-04T17:30:00Z"}
    decision={"lineup":{"starters":[{"element":x,"position":"MID"} for x in range(1,12)],"captain":{"element":1},"vice_captain":{"element":2}}}
    team={"squad":[{"element":x,"position":"MID"} for x in range(1,16)],"authority":"user_lock"}
    comparator={"contract":"OWNED_CHALLENGER_COMPARATOR_V1","top_comparisons":[{"player_out":{"element":1},"player_in":{"element":20},"classification":"WATCH_CHALLENGER","transfer_economics":{}}]}
    first=capture(context,decision,team,comparator,now=datetime(2026,8,29,4,0,tzinfo=timezone.utc))
    second=capture(context,decision,team,comparator,previous=first,now=datetime(2026,8,30,4,0,tzinfo=timezone.utc))
    assert first["last_capture"]["status"] == "PREDEADLINE_CAPTURED"
    assert second["last_capture"]["status"] == "ALREADY_FROZEN"
    assert second["records"]["3"]["captured_at"] == first["records"]["3"]["captured_at"]
    actual={1:{"points":2},20:{"points":10},**{x:{"points":3} for x in range(2,16)}}
    settled=decision_regret(first["records"]["3"],actual)
    transfer=settled["transfer_comparator_realized_net_gain"]
    assert transfer["status"] == "PARTIAL_GROSS_ONLY"
    assert transfer["value"] is None
    assert transfer["comparisons"][0]["realized_gross_points_delta_1gw"] == 8.0
