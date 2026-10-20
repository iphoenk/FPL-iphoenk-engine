from __future__ import annotations

from src.engines.v12_report_production_gate import evaluate_report_production_gate


SECTION_IDS = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
    "S07", "S08", "S09", "S10", "S11", "S12", "S13",
    "S14", "S14B", "S15", "S15B", "S16",
    "S17", "S18", "S19",
]


def _coverage_fixtures():
    stamp = "2026-09-30T20:00:00+07:00"
    categories = [
        {"category": category, "result": "CHECKED_NO_CHANGE",
         "attempted_at": stamp, "source_url": "https://example.com/" + category.lower()}
        for category in (
            "OFFICIAL_PL_FPL", "OFFICIAL_CLUBS", "OFFICIAL_SOCIAL",
            "BEAT_REPORTERS_NEWS", "INDEPENDENT_ANALYTICS",
            "FPL_COMMUNITY", "USER_SUPPLIED_LEADS",
        )
    ]
    clubs = [
        {"official_club_id": str(i), "club_name": "Club " + str(i),
         "result": "CHECKED_NO_CHANGE", "attempted_at": stamp,
         "evidence_url": "https://example.com/club/" + str(i)}
        for i in range(1, 21)
    ]
    assessments = []
    for domain in (
        "PLAYER_MINUTES", "STARTING_XI_FORMATION", "CAPTAIN_VICE",
        "TRANSFER_HOLD_HITS", "COMPETITIVE_WINDOW",
    ):
        assessments.append({
            "domain": domain, "verdict": "CONFIRMS", "action": "HOLD",
            "sources": [
                {"url": "https://example.com/source-a/" + domain.lower(),
                 "as_of": stamp, "independence_group": "a"},
                {"url": "https://example.net/source-b/" + domain.lower(),
                 "as_of": stamp, "independence_group": "b"},
            ],
        })
    return (
        {"scan_id": "test-scan", "scan_at": stamp,
         "deadline": "2026-10-01T17:00:00+07:00",
         "deadline_source_url": "https://example.com/official-deadline",
         "categories": categories, "clubs": clubs},
        {"assessment_at": stamp, "assessments": assessments},
    )


def _bundle():
    news_coverage, counterpart_coverage = _coverage_fixtures()
    sections = []
    for section_id in SECTION_IDS:
        content = {"presentation_status": "CURRENT"}
        if section_id == "S01":
            content["decision"] = "WAIT"
        elif section_id == "S19":
            content["decision"] = "WAIT"
            content["final_judgement"] = "WAIT. Preserve squad."
        elif section_id == "S02":
            content["rows"] = [
                {"element_id": value, "player": f"P{value}"}
                for value in range(1, 16)
            ]
        sections.append(
            {
                "section_id": section_id,
                "label": section_id,
                "state": "COMPLETE",
                "content": content,
            }
        )
    return {
        "report_mode": "DEEP",
        "report_slot": "2026-09-30T21:30:00+07:00",
        "planning_gw": 6,
        "runner_status": "PASS",
        "delivery_status": "READY_FULL",
        "s16b_due": False,
        "section_manifest": [{"section_id": value} for value in SECTION_IDS],
        "pre_render_qa": {"status": "PASS"},
        "post_render_qa": {"status": "PASS"},
        "human_facing_qa": {"status": "PASS"},
        "execution_proof": {
            "prior_analytics_relabelled_fresh": False,
        },
        "news_source_coverage": news_coverage,
        "independent_counterpart_coverage": counterpart_coverage,
        "report": {"sections": sections},
    }


def _presentation_qa():
    return {
        "section_count": 22,
        "expected_section_count": 22,
        "s16b_due": False,
        "section_order_exact": True,
        "our15_count": 15,
        "our15_complete_when_claimed": True,
        "watchlist_state": "COMPLETE",
        "watchlist_exact20_when_claimed": True,
        "rise20_state": "COMPLETE",
        "rise20_eta_contract": True,
        "fall20_state": "COMPLETE",
        "fall20_eta_contract": True,
        "all15_count": 15,
        "all15_complete_when_claimed": True,
        "root_failure_count": 0,
        "downstream_false_failures": 0,
        "prior_without_source_occurrence": False,
        "decision_first": True,
        "technical_health_in_s17": True,
        "final_judgement_present": True,
        "visible_report_body_non_empty": True,
    }


def _serving():
    return {
        "delivery_status": "READY_FULL",
        "decision": "WAIT",
        "s16b_due": False,
        "sections": {
            section_id: {"state": "COMPLETE", "content": {}}
            for section_id in SECTION_IDS
        },
    }


def test_report_production_gate_is_independent_of_engineering_closure():
    result = evaluate_report_production_gate(
        _bundle(),
        presentation_qa=_presentation_qa(),
        serving_snapshot=_serving(),
        visible_body_non_empty=True,
    )
    assert result["status"] == "PASS"
    assert result["report_delivery_allowed"] is True
    assert result["engineering_closure_required_for_publish"] is False
    assert "P4_SCENARIO_PACKAGE" in result["engineering_requirements"]


def test_report_production_gate_rejects_false_prior_as_current():
    bundle = _bundle()
    s14 = next(
        row for row in bundle["report"]["sections"]
        if row["section_id"] == "S14"
    )
    s14["content"]["prior_source_occurrence"] = "2026-09-29T21:30:00+07:00"

    result = evaluate_report_production_gate(
        bundle,
        presentation_qa=_presentation_qa(),
        serving_snapshot=_serving(),
        visible_body_non_empty=True,
    )
    assert result["status"] == "FAIL"
    assert "S14:PRIOR_RELABELED_CURRENT" in result["failures"]


def test_report_production_gate_rejects_s01_s19_mismatch():
    bundle = _bundle()
    s19 = next(
        row for row in bundle["report"]["sections"]
        if row["section_id"] == "S19"
    )
    s19["content"]["decision"] = "ACT"
    s19["content"]["final_judgement"] = "ACT. Execute transfer."

    result = evaluate_report_production_gate(
        bundle,
        presentation_qa=_presentation_qa(),
        serving_snapshot=_serving(),
        visible_body_non_empty=True,
    )
    assert result["status"] == "FAIL"
    assert "S01_S19_DECISION_MISMATCH" in result["failures"]



def test_runner_pass_without_delivery_status_cannot_bypass_coverage_gate():
    bundle = _bundle()
    bundle.pop("delivery_status", None)
    bundle.pop("news_source_coverage", None)
    bundle.pop("independent_counterpart_coverage", None)
    result = evaluate_report_production_gate(
        bundle,
        presentation_qa=_presentation_qa(),
        serving_snapshot=_serving(),
        visible_body_non_empty=True,
    )
    assert result["status"] == "FAIL"
    assert "SOURCE_SCAN_TIMESTAMP_MISSING" in result["failures"]
    assert "COUNTERPART_ASSESSMENT_TIMESTAMP_MISSING" in result["failures"]

    # Classified delivery can be safely DEGRADED, never falsely FULL. The
    # production source gate above is intentionally NOT relaxed.
    from src.engines.v12_delivery_reliability import downgrade_missing_source_evidence
    incomplete = _bundle()
    incomplete.pop("news_source_coverage")
    incomplete.pop("independent_counterpart_coverage")
    downgrade_missing_source_evidence(incomplete)
    assert incomplete["runner_status"] == "PARTIAL"
    assert incomplete["root_failure"] == "SOURCE_EVIDENCE_INCOMPLETE"
    assert incomplete["source_evidence_status"] == "FAIL"
    assert "SOURCE_SCAN_TIMESTAMP_MISSING" in incomplete["source_evidence_failures"]
    assert "COUNTERPART_ASSESSMENT_TIMESTAMP_MISSING" in incomplete["source_evidence_failures"]
    assert incomplete["execution_proof"]["canonical_analytics_status"] == "PASS"
    assert incomplete["execution_proof"]["source_evidence_is_natural_proof"] is False

    complete = _bundle()
    downgrade_missing_source_evidence(complete)
    assert complete["runner_status"] == "PASS"
    assert "source_evidence_status" not in complete

    from src.engines.v12_stage3_acceptance import _source_gap_only_analytics_pass
    # The Stage3 bridge is limited to exactly reproducible, nonfabricated
    # source failures. It never treats arbitrary PARTIAL as mathematical PASS.
    incomplete["delivery_status"] = "READY_DEGRADED"
    assert _source_gap_only_analytics_pass(incomplete) is True
    incomplete["execution_proof"]["source_evidence_failures"] = ["FAKE_PASS"]
    assert _source_gap_only_analytics_pass(incomplete) is False
    incomplete["execution_proof"]["source_evidence_failures"] = incomplete["source_evidence_failures"]
    incomplete["source_evidence_failures"].append("FAKE_MISSING_SOURCE")
    assert _source_gap_only_analytics_pass(incomplete) is False
    incomplete["source_evidence_failures"].pop()
    incomplete["execution_proof"]["canonical_analytics_status"] = "FAIL"
    assert _source_gap_only_analytics_pass(incomplete) is False
    assert _source_gap_only_analytics_pass(complete) is False

def test_source_coverage_rejects_duplicate_categories_and_counterpart_domains():
    # A duplicate may not overwrite an original CHECKED row in a dict.
    from copy import deepcopy
    from src.engines.v12_source_coverage import (
        validate_news_source_coverage,
        validate_independent_counterpart_coverage,
    )

    news, counterpart = _coverage_fixtures()
    assert validate_news_source_coverage(news)["status"] == "PASS"
    assert validate_independent_counterpart_coverage(counterpart)["status"] == "PASS"

    duplicate_news = deepcopy(news)
    duplicate_news["categories"].append(dict(duplicate_news["categories"][0]))
    result = validate_news_source_coverage(duplicate_news)
    assert result["status"] == "FAIL"
    assert "SOURCE_CATEGORY_DUPLICATE:OFFICIAL_PL_FPL" in result["failures"]

    duplicate_counterpart = deepcopy(counterpart)
    duplicate_counterpart["assessments"].append(
        dict(duplicate_counterpart["assessments"][0])
    )
    result = validate_independent_counterpart_coverage(duplicate_counterpart)
    assert result["status"] == "FAIL"
    assert "COUNTERPART_DOMAIN_DUPLICATE:PLAYER_MINUTES" in result["failures"]


def test_counterpart_assessment_timestamp_must_be_parsable(tmp_path):
    from src.engines.v12_source_coverage import (
        validate_independent_counterpart_coverage,
    )
    _, counterpart = _coverage_fixtures()
    counterpart["assessment_at"] = "not-an-iso-timestamp"
    result = validate_independent_counterpart_coverage(counterpart)
    assert result["status"] == "FAIL"
    assert "COUNTERPART_ASSESSMENT_TIMESTAMP_MISSING" in result["failures"]

    # This fixture represents acquisition telemetry only; it can never prove
    # seven categories, 20 separate club news checks, or independent reviews.
    import json
    from src.engines.v12_v6_source_trace import build_v6_source_trace
    slot = "2026-10-20T10:52:00+07:00"
    stamp = "2026-10-20T03:53:50+00:00"
    fixture_files = {
        "data/v6/health/publish_integrity.json": {
            "status": "PASS", "logical_slot": slot, "run_id": "39366647541",
        },
        "data/v6/evidence/latest_index.json": {
            "generated_at": stamp,
            "sources": [
                {"source_id": "official_fpl", "checked_at": stamp,
                 "health": "GREEN", "availability": "AVAILABLE",
                 "source_snapshot_ids": ["official_fpl:bootstrap:testhash"],
                 "path": "data/v6/current/official_fpl.json"}
            ],
        },
        "data/v6/evidence/resolved_registry.json": {
            "sources": [{"id": "official_fpl", "category": "factual_authority"}]
        },
        "data/v6/normalized/canonical_teams.json": {
            "authority": "official_fpl", "team_count": 20,
            "teams": [{"official_fpl_team_id": i} for i in range(1, 21)],
        },
    }
    for relative_path, payload in fixture_files.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=slot)
    assert trace["status"] == "PASS"
    assert trace["provider_count"] == 1
    assert trace["official_club_identity_count"] == 20
    assert trace["sufficient_for_full_source_gate"] is False
    assert trace["club_news_verification"] == "NOT_PROVEN"
    assert trace["seven_category_news_scan"] == "NOT_PROVEN"
    assert trace["five_domain_independent_counterpart"] == "NOT_PROVEN"

    # Real V6 observations are never accepted for a different occurrence.
    wrong = build_v6_source_trace(
        runtime_data_root=tmp_path, report_slot="2026-10-20T12:30:00+07:00"
    )
    assert wrong["status"] == "FAIL"
    assert "V6_PUBLICATION_SLOT_MISMATCH" in wrong["failures"]
    assert wrong["providers"] == []

    # Neither a forged PASS nor a mismatched identity count can leak proof.
    fixture_files["data/v6/health/publish_integrity.json"]["status"] = "FAIL"
    file = tmp_path / "data/v6/health/publish_integrity.json"
    file.write_text(json.dumps(fixture_files["data/v6/health/publish_integrity.json"]), encoding="utf-8")
    unverified = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=slot)
    assert unverified["status"] == "FAIL"
    assert unverified["providers"] == []

    # The deadline is real only with the exact V6 publication, official
    # bootstrap snapshot ID and an authentic GW event field.
    from src.engines.v12_v6_source_trace import bind_official_deadline
    fixture_files["data/v6/health/publish_integrity.json"]["status"] = "PASS"
    file.write_text(
        json.dumps(fixture_files["data/v6/health/publish_integrity.json"]),
        encoding="utf-8",
    )
    valid_trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=slot)
    registry_file = tmp_path / "data/v6/evidence/resolved_registry.json"
    registry = fixture_files["data/v6/evidence/resolved_registry.json"]
    registry["sources"][0]["requests"] = [{
        "id": "bootstrap",
        "url": "https://fantasy.premierleague.com/api/bootstrap-static/",
    }]
    registry_file.write_text(json.dumps(registry), encoding="utf-8")
    bootstrap = {"events": [{"id": 8, "deadline_time": "2026-10-24T11:00:00Z"}]}
    exact = bind_official_deadline(
        valid_trace, bootstrap=bootstrap, planning_gw=8,
        report_slot=slot, runtime_data_root=tmp_path,
    )
    assert exact["official_deadline_check"] == "VERIFIED_FPL_BOOTSTRAP_FIELD"
    assert exact["official_deadline_evidence"]["deadline_wib"] == "2026-10-24T18:00:00+07:00"
    assert exact["seven_category_news_scan"] == "NOT_PROVEN"
    assert exact["sufficient_for_full_source_gate"] is False

    wrong_gw = bind_official_deadline(
        valid_trace, bootstrap=bootstrap, planning_gw=9,
        report_slot=slot, runtime_data_root=tmp_path,
    )
    assert wrong_gw["official_deadline_check"] == "NOT_PROVEN"
    no_source = dict(valid_trace)
    no_source["providers"] = []
    failed = bind_official_deadline(
        no_source, bootstrap=bootstrap, planning_gw=8,
        report_slot=slot, runtime_data_root=tmp_path,
    )
    assert failed["official_deadline_check"] == "NOT_PROVEN"

    # Official deadline proof closes only two missing fields, not news coverage.
    from src.engines.v12_v6_source_trace import (
        verified_official_deadline_source_coverage,
    )
    from src.engines.v12_source_coverage import validate_news_source_coverage
    coverage = verified_official_deadline_source_coverage(exact)
    assert coverage["deadline"] == "2026-10-24T11:00:00+00:00"
    assert coverage["deadline_gw"] == 8
    assert "scan_at" not in coverage
    assert "scan_id" not in coverage
    assert "categories" not in coverage
    assert "clubs" not in coverage
    source_gate = validate_news_source_coverage(coverage, require_full=True)
    assert source_gate["status"] == "FAIL"
    assert "OFFICIAL_DEADLINE_MISSING" not in source_gate["failures"]
    assert "OFFICIAL_DEADLINE_SOURCE_MISSING" not in source_gate["failures"]
    assert "SOURCE_SCAN_ID_MISSING" in source_gate["failures"]
    assert "SOURCE_CATEGORY_MISSING:OFFICIAL_CLUBS" in source_gate["failures"]
    assert "ALL_20_CLUBS_IDENTITY_COVERAGE_INVALID" in source_gate["failures"]
    for invalid in (wrong_gw, failed, unverified):
        assert verified_official_deadline_source_coverage(invalid) == {}
    false_proof = dict(exact)
    false_proof["official_deadline_check"] = "NOT_PROVEN"
    assert verified_official_deadline_source_coverage(false_proof) == {}

