import json
from datetime import datetime, timezone
from pathlib import Path

from src.engines.v4_checkpoint_governance import govern_checkpoint
from src.services.orchestrator import _service_levels


ROOT = Path(__file__).resolve().parents[1]


def _governance_fixture(age_minutes=0):
    now = datetime(2026, 8, 28, 0, 45, tzinfo=timezone.utc)
    generated = datetime.fromtimestamp(now.timestamp() - age_minutes * 60, timezone.utc).isoformat()
    latest = {
        "generated_at": generated,
        "squad_authority": "LOCKED_PRE_DEADLINE",
        "checkpoint_context": {
            "policy_id": "DEEP_REVIEW_0430",
            "is_simulation": False,
            "is_final_review": False,
            "post_final_emergency_only": False,
            "max_snapshot_age_minutes": 60,
            "report_scope": ["locked_15"],
        },
    }
    health = {
        "overall": "GREEN",
        "pipeline_health": "GREEN",
        "prediction_health": "AMBER",
        "decision_engine": "PROVISIONAL",
        "go_allowed": False,
        "gate0": {"pass": True},
        "critical_partial": [],
        "critical_warmup": ["DSS-44", "DSS-X12"],
        "capability_coverage": {"active": 62, "partial": 10, "warmup": 2, "failed": 0, "declared": 74},
    }
    sanity = {
        "final_verdict": "MATERIAL_UPGRADE",
        "raw_package_verdict": "MATERIAL_UPGRADE",
        "recommended_package": {
            "material_eligible": True,
            "replacements": 2,
            "out": [{"name": "A"}, {"name": "B"}],
            "in": [{"name": "C"}, {"name": "D"}],
        },
    }
    effective = {
        "authority": "USER_OVERRIDE",
        "status": "MANUAL_DRAFT_ADJUSTABLE",
        "formation": "3-5-2",
        "captain": {"name": "Captain"},
        "vice_captain": {"name": "Vice"},
        "chip_context": {"active_chip": "WILDCARD"},
    }
    locked = {"wildcard_active": True, "target_gw": 2, "players": [{"element": n} for n in range(15)]}
    scorecard = {
        "planning_gw": {
            "status": "PROJECTION",
            "gw": 2,
            "active_chip": "WILDCARD",
            "human_override_active": True,
            "engine_comparison": {"user_minus_engine_xpts": -1.82},
            "squad_basis": {
                "planning_gw": 2,
                "baseline_gw": 1,
                "override_applied": True,
                "override_target_gw": 2,
                "effective_authority": "LOCKED_PRE_DEADLINE",
                "authority_source": "USER_CAPTURED_WC_DRAFT",
            },
        },
    }
    return now, latest, health, sanity, effective, locked, scorecard


def test_report_language_policy_is_cross_engine_and_hides_technical_reasons():
    policy = json.loads((ROOT / "config/report_language_policy.json").read_text())
    assert policy["cross_engine_scope"] == ["V3", "V4", "V5"]
    assert policy["guardrails"]["primary_reasoning_plain_fpl_language"] is True
    now, latest, health, sanity, effective, locked, scorecard = _governance_fixture()
    out = govern_checkpoint(latest, health, sanity, effective, locked, scorecard=scorecard, now=now)
    assert out["action_state"] == "HOLD"
    assert "CRITICAL_PREDICTION_WARMUP" in out["readiness"]["reasons"]
    human = out["human_report"]
    assert human["language_policy"] == "fpl_human_report_language_v1"
    primary = " ".join([*human["why"], *human["what_to_do"]]).lower()
    for marker in policy["technical_terms_forbidden_in_primary_reasoning"]:
        assert marker.lower() not in primary
    assert "struktur tim" in primary


def test_stale_report_is_human_refresh_required_not_technical_excuse():
    policy = json.loads((ROOT / "config/report_language_policy.json").read_text())
    now, latest, health, sanity, effective, locked, scorecard = _governance_fixture(age_minutes=61)
    out = govern_checkpoint(latest, health, sanity, effective, locked, scorecard=scorecard, now=now)
    assert out["action_state"] == "REFRESH_REQUIRED"
    assert "SNAPSHOT_STALE" in out["readiness"]["reasons"]
    primary = " ".join([*out["human_report"]["why"], *out["human_report"]["what_to_do"]]).lower()
    assert "data terakhir" in primary
    for marker in policy["technical_terms_forbidden_in_primary_reasoning"]:
        assert marker.lower() not in primary


def test_official_fpl_fields_are_preserved_without_downstream_refetch():
    enrichment = (ROOT / "src/services/enrichment_service.py").read_text()
    prediction = (ROOT / "src/services/prediction_service.py").read_text()
    postflight = (ROOT / "src/services/framework_postflight_truth_service.py").read_text()
    for field in (
        "selected_by_percent", "expected_goals", "expected_assists", "expected_goal_involvements",
        "expected_goals_conceded", "bps", "bonus", "form", "starts",
    ):
        assert field in enrichment
    assert "raw_snapshot.official.bootstrap+fixtures" in prediction
    assert '"effective_ownership_available_from_official_fpl": False' in prediction
    assert "src.sources.official_fpl" not in enrichment
    assert "src.sources.official_fpl" not in prediction
    for module_id in ("DSS-18", "DSS-20", "DSS-21", "DSS-22", "DSS-23", "DSS-38"):
        assert f'"{module_id}"' in postflight
    assert "DSS-41" in postflight
    assert "effective ownership" in postflight.lower()


def test_schedule_only_capabilities_are_not_falsely_promoted_from_official_fpl():
    source = (ROOT / "src/services/framework_postflight_truth_service.py").read_text()
    assert 'module_id in {"DSS-30", "DSS-31", "DSS-32", "DSS-33"}' in source
    assert "Premier League matches only" in source
    for module_id in ("DSS-30", "DSS-31", "DSS-32", "DSS-33"):
        assert f'"{module_id}"' in source


def test_dag_parallelization_only_groups_dependency_independent_services():
    registry = json.loads((ROOT / "config/service_registry.json").read_text())
    levels = _service_levels(registry)
    assert registry["execution_model"] == "process_isolated_dag_parallel_single_host"
    assert any({row["id"] for row in level} == {"validation_lifecycle", "rules_compliance"} for level in levels)
    assert any({row["id"] for row in level} == {"personal_gw_scorecard", "framework_postflight"} for level in levels)
    for level in levels:
        ids = {row["id"] for row in level}
        for row in level:
            assert not (set(row.get("depends_on") or []) & ids)


def test_recovery_workflow_covers_all_three_checkpoints_and_skips_fresh_data():
    workflow = (ROOT / ".github/workflows/fpl-engine-recovery.yml").read_text()
    assert 'cron: "45 21 * * *"' in workflow
    assert 'cron: "45 5 * * *"' in workflow
    assert 'cron: "45 14 * * *"' in workflow
    assert "age_minutes <= 45" in workflow
    assert "Recover 11-service production snapshot" in workflow
    assert "Centralized production quality gate" in workflow
    assert "recover missed scheduled checkpoint" in workflow


def test_contracts_make_v495_behaviour_mandatory():
    contracts = json.loads((ROOT / "config/service_contract_registry.json").read_text())
    assert contracts["contracts"]["enrichment"]["min_schema_version"] == 495
    assert contracts["contracts"]["latest_snapshot"]["version_prefix"] == "4.9.5-official-first-reporting"
    assert contracts["contracts"]["checkpoint_decision"]["version_prefix"] == "v4.9.5-checkpoint-governance-human-report"
    required = set(contracts["contracts"]["framework_postflight"]["required_paths"])
    assert {"official_fpl_first.status", "official_fpl_first.promoted_modules", "official_fpl_first.promoted_count"} <= required
