"""Regression: S06 visual badges copy S08 authority without changing lineup math."""
from copy import deepcopy

from src.engines.v12_report_orchestration import _bind_s06_captain_from_s08


def _sections(vice_id=2, selected=(1, 2, 3)):
    return [
        {
            "section_id": "S06", "state": "COMPLETE",
            "content": {
                "starting_xi": [{"element": i} for i in selected],
                "captain": {"element_id": 1, "player": "P1"},
                "vice_captain": {"element_id": 3, "player": "P3"},
                "captain_adjusted_xpts": 53.459669,
                "formation": "5-3-2",
            },
        },
        {
            "section_id": "S08", "state": "COMPLETE",
            "content": {
                "captain": {"element_id": 1, "player": "P1"},
                "vice_captain": {"element_id": vice_id, "player": "P2"},
            },
        },
    ]


def test_pitch_vice_copies_canonical_s08_without_changing_optimizer():
    sections = _sections()
    before = deepcopy(sections[0]["content"])
    _bind_s06_captain_from_s08(sections)
    pitch = sections[0]["content"]
    assert pitch["vice_captain"]["element_id"] == 2
    assert pitch["captain_vice_presentation_authority"] == "S08_CANONICAL_COPY"
    assert pitch["starting_xi"] == before["starting_xi"]
    assert pitch["captain_adjusted_xpts"] == before["captain_adjusted_xpts"]
    assert pitch["formation"] == before["formation"]


def test_pitch_does_not_copy_vice_outside_selected_xi():
    sections = _sections(vice_id=99)
    _bind_s06_captain_from_s08(sections)
    assert sections[0]["content"]["vice_captain"]["element_id"] == 3
    assert "captain_vice_presentation_authority" not in sections[0]["content"]


def test_pitch_does_not_copy_duplicate_captain_and_vice():
    sections = _sections(vice_id=1)
    _bind_s06_captain_from_s08(sections)
    assert sections[0]["content"]["vice_captain"]["element_id"] == 3
