from src.engines.report_enrichment import _apply_readiness_and_actionability


def _base_user():
    return {
        "action_board": [
            {"action": "HOLD", "subject": "Squad", "trigger": "model"},
            {"action": "HOLD", "subject": "Chip", "trigger": "legality"},
            {"action": "LOCK", "subject": "Captain: X", "trigger": "model"},
        ]
    }


def _base_tech():
    return {
        "framework_health": {
            "overall": "GREEN",
            "go_allowed": True,
            "critical_failed": [],
        },
        "audit": {},
    }


def test_unsettled_model_is_advisory_but_fact_constraint_remains_actionable():
    user = _base_user()
    tech = _base_tech()
    latest = {
        "prediction_evaluation": {
            "status": "NO_SETTLED_SAMPLE",
            "sample_size": 0,
            "settled_gameweeks": [],
            "dynamic_weight_eligible": False,
        }
    }
    report_time = {"status": "REFRESH_REQUIRED", "web_refresh_required": True}

    _apply_readiness_and_actionability(user, tech, latest, report_time)

    assert user["readiness"]["engine"] == "ENGINE_READY"
    assert user["readiness"]["final_report_evidence"] == "FINAL_REPORT_EVIDENCE_PENDING"
    assert user["readiness"]["predictive_validation"]["model_derived_actionability"] == "GATED"

    rows = {row["subject"]: row for row in user["action_board"]}
    assert rows["Chip"]["action_class"] == "FACT_CONSTRAINT"
    assert rows["Chip"]["actionability"] == "ACTIONABLE"
    assert rows["Squad"]["action_class"] == "MODEL_DERIVED"
    assert rows["Squad"]["actionability"] == "ADVISORY_UNTIL_SETTLED_VALIDATION"
    assert rows["Captain: X"]["actionability"] == "ADVISORY_UNTIL_SETTLED_VALIDATION"


def test_eligible_settled_model_activates_model_actionability_and_ready_external_evidence():
    user = _base_user()
    tech = _base_tech()
    latest = {
        "prediction_evaluation": {
            "status": "SETTLED",
            "sample_size": 100,
            "settled_gameweeks": [2, 3],
            "dynamic_weight_eligible": True,
        }
    }
    report_time = {"status": "READY", "web_refresh_required": False}

    _apply_readiness_and_actionability(user, tech, latest, report_time)

    assert user["readiness"]["final_report_evidence"] == "FINAL_REPORT_EVIDENCE_READY"
    assert user["readiness"]["predictive_validation"]["model_derived_actionability"] == "ACTIVE"
    for row in user["action_board"]:
        assert row["actionability"] == "ACTIONABLE"


def test_engine_readiness_is_independent_from_external_report_evidence():
    user = _base_user()
    tech = {
        "framework_health": {
            "overall": "AMBER",
            "go_allowed": False,
            "critical_failed": ["example"],
        },
        "audit": {},
    }
    latest = {"prediction_evaluation": {"sample_size": 0, "dynamic_weight_eligible": False}}
    report_time = {"status": "READY", "web_refresh_required": False}

    _apply_readiness_and_actionability(user, tech, latest, report_time)

    assert user["readiness"]["engine"] == "ENGINE_REVIEW_REQUIRED"
    assert user["readiness"]["final_report_evidence"] == "FINAL_REPORT_EVIDENCE_READY"
