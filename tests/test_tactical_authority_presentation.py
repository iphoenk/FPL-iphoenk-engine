from __future__ import annotations

from src.engines.report_serving_validate import _tactical_presentation_note


def _tactical(highlight: str) -> dict:
    return {
        "evidence_state": "CUKUP",
        "highlights": [highlight],
    }


def test_user_override_captain_is_never_mislabeled_as_engine_captain():
    payload = {
        "gameweek_context": {
            "planning": {
                "decision_authority": "USER_OVERRIDE",
                "captain": {"element": 426, "name": "B.Fernandes"},
                "vice_captain": {"element": 411, "name": "Haaland"},
            }
        },
        "owned_squad": {
            "facts": [
                {
                    "element": 426,
                    "name": "B.Fernandes",
                    "tactical_matchup": _tactical("Bruno matchup material"),
                },
                {
                    "element": 411,
                    "name": "Haaland",
                    "tactical_matchup": _tactical("Haaland matchup material"),
                },
            ]
        },
        "starting_xi": {
            "model": {
                "battle": {
                    "starter": "Robinson",
                    "challenger": "Rogers",
                    "leader_metrics": {"tactical_matchup": _tactical("Robinson matchup material")},
                    "challenger_metrics": {"tactical_matchup": _tactical("Rogers matchup material")},
                }
            }
        },
        "captaincy": {
            "model": {
                "captain": {"element": 411, "name": "Haaland", "tactical_matchup": _tactical("Haaland matchup material")},
                "vice": {"element": 115, "name": "De Cuyper", "tactical_matchup": _tactical("Vice matchup material")},
            }
        },
    }

    text = _tactical_presentation_note(payload)
    assert "Battle XI Robinson vs Rogers: Robinson matchup material" in text
    assert "Kapten aktif B.Fernandes: Bruno matchup material" in text
    assert "Kapten Haaland:" not in text


def test_engine_authority_can_label_model_captain_normally():
    payload = {
        "gameweek_context": {
            "planning": {
                "decision_authority": "ENGINE_RECOMMENDATION",
                "captain": {"element": 411, "name": "Haaland"},
            }
        },
        "owned_15": [],
        "captaincy": {
            "model": {
                "captain": {"element": 411, "name": "Haaland", "tactical_matchup": _tactical("Haaland matchup material")},
                "vice": {},
            }
        },
    }

    text = _tactical_presentation_note(payload)
    assert "Kapten Haaland: Haaland matchup material" in text
    assert "Kapten aktif" not in text
