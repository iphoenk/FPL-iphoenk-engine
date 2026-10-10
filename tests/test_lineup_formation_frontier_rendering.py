"""The S06 pitch exposes exact P1.7 formation winners, not simulated swaps.

All numeric fixtures here are synthetic except the first two known baseline
examples. The renderer has no scoring, transfer or captain decision authority.
"""
from src.engines.v12_mobile_pitch import (
    render_s06_formation_frontier,
    render_s06_pitch,
)


def _examples():
    return [
        {"formation": "5-4-1", "expected_fpl_points_with_captain_vice": 55.203771, "selected": True},
        {"formation": "4-4-2", "expected_fpl_points_with_captain_vice": 55.166847},
        {"formation": "5-3-2", "expected_fpl_points_with_captain_vice": 54.9},
        {"formation": "3-5-2", "expected_fpl_points_with_captain_vice": 54.8},
        {"formation": "3-4-3", "expected_fpl_points_with_captain_vice": 53.2},
        {"formation": "4-3-3", "expected_fpl_points_with_captain_vice": 52.6},
        {"formation": "4-5-1", "expected_fpl_points_with_captain_vice": 52.4},
        {"formation": "5-2-3", "expected_fpl_points_with_captain_vice": 52.1},
    ]


def test_s06_shows_full_canonical_frontier_not_only_two_rows():
    body = render_s06_pitch({
        "formation": "5-4-1",
        "starting_xi": [],
        "formation_comparison": _examples(),
    })
    for formation in ("3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"):
        assert f"<td>{formation}</td>" in body
    assert "53.200" in body
    assert "55.204" in body
    assert "DCL to Barry" in body
    assert "DCL to Gonzalo" in body
    assert "Not yet simulated" in body


def test_s06_missing_evidence_fails_soft_without_fabrication():
    body = render_s06_pitch({"formation": "5-4-1", "starting_xi": []})
    assert "Formation comparison: UNAVAILABLE" in body
    assert "53.200" not in body


def test_s06_marks_requested_formations_absent_from_p17():
    body = render_s06_formation_frontier({
        "formation_comparison": _examples()[:2],
    })
    assert "Missing in canonical CURRENT15: " in body
    for formation in ("3-5-2", "5-3-2", "3-4-3", "4-3-3", "4-5-1", "5-2-3"):
        assert formation in body


def test_s06_escapes_untrusted_names():
    body = render_s06_formation_frontier({
        "formation_comparison": [
            {"formation": "<script>alert('x')</script>", "expected_fpl_points_with_captain_vice": 3.0}
        ],
    })
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
