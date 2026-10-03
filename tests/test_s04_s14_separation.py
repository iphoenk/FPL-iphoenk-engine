from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines


def _s04_payload():
    joao = {
        "subject": "Joao Pedro",
        "headline": "Availability uncertainty worsened",
        "summary": "Availability uncertainty worsened",
        "source_class": "OFFICIAL",
        "source_name": "Official FPL",
        "published_or_observed_timestamp": "2026-10-03T12:00:00+07:00",
        "affected_player_team": {"element_id": 1, "team_id": 1},
        "evidence_status": "CONFIRMED_OFFICIAL_FPL_FEED",
        "decision_relevance": "AVAILABILITY / MINUTES MONITOR",
        "audience": "OUR15",
        "news_observation_is_model_update": False,
        "act_authority": False,
    }
    mbeumo = {
        "classification": "IMPROVED",
        "source_class": "MODEL_SIGNAL",
        "scope": "WATCHLIST / TARGETS",
        "subject": "Mbeumo",
        "summary": "Role signal improved in the bound football model",
        "evidence_time": "2026-10-03T12:30:00+07:00",
        "news_observation_is_model_update": False,
        "act_authority": False,
    }
    return {
        "news_summary": "MATERIAL NEWS PRESENT",
        "material_news": [joao],
        "news_groups": {
            "OUR15": [joao],
            "WATCHLIST / TARGETS": [],
            "TEAM / TACTICAL": [],
            "OTHER MATERIAL": [],
        },
        "model_developments": [mbeumo],
        "decision_consequence": {
            "transfer_state": "HOLD",
            "xi_state": "REVIEW",
            "captain_state": "LOCK",
            "price_state": "MONITOR",
            "news_self_authorizes_act": False,
            "news_observation_is_model_update": False,
            "model_numbers_mutated_here": False,
            "optimizer_authority_remains_s14": True,
        },
        "source_policy": {
            "allowed_source_classes": [
                "OFFICIAL",
                "RELIABLE_REPORT",
                "MULTIPLE_CREDIBLE_REPORTS",
                "RUMOR / UNVERIFIED",
                "MODEL_SIGNAL",
                "INFERENCE",
            ],
            "rumor_is_fact": False,
            "rumor_may_authorize_act": False,
            "news_observation_equals_model_update": False,
        },
        "changes": [mbeumo],
    }


def test_s04_can_show_material_changes_while_transfer_state_remains_hold():
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S04",
        content=_s04_payload(),
        owned_ids={1},
        owned_names={1: "Joao Pedro"},
    )
    body = "\n".join(lines)

    assert "Joao Pedro" in body
    assert "Availability uncertainty worsened" in body
    assert "Role signal improved in the bound football model" in body
    assert "TRANSFER=HOLD" in body
    assert "NEWS SELF-AUTHORIZES ACT: False" in body
    assert "OPTIMIZER AUTHORITY REMAINS S14: True" in body


def test_s14_rejects_news_dump_even_when_route_verdict_is_hold():
    report = {
        "sections": [
            {
                "section_id": "S14",
                "state": "COMPLETE",
                "content": {
                    "package_routes": [{"route": "HOLD"}],
                    "frontier": [{"route": "HOLD"}],
                    "material_news": [
                        {
                            "subject": "Joao Pedro",
                            "summary": "Availability worsened",
                        }
                    ],
                },
            }
        ]
    }
    failures = validate_deep_decision_content_delivery(
        report,
        "PACKAGE OPTIMIZER / TRANSFER FRONTIER\nHOLD",
    )
    assert "S14_NEWS_DUMP_FORBIDDEN=material_news" in failures


def test_s14_clean_hold_does_not_trigger_news_dump_guard():
    report = {
        "sections": [
            {
                "section_id": "S14",
                "state": "COMPLETE",
                "content": {
                    "package_routes": [{"route": "HOLD"}],
                    "frontier": [{"route": "HOLD"}],
                },
            }
        ]
    }
    failures = validate_deep_decision_content_delivery(
        report,
        "PACKAGE OPTIMIZER / TRANSFER FRONTIER\nHOLD",
    )
    assert not any(
        failure.startswith("S14_NEWS_DUMP_FORBIDDEN")
        for failure in failures
    )
