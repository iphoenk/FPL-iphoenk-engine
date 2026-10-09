from __future__ import annotations

from src.engines.v12_mobile_pitch import render_s06_pitch


def _content():
    return {
        "formation": "5-4-1",
        "starting_xi": [
            {"element": 1, "name": "Haaland", "position": "FWD"},
            {"element": 2, "name": "Bruno Fernandes", "position": "MID", "is_captain": True},
            {"element": 3, "name": "Martin Odegaard", "position": "MID", "is_vice_captain": True},
            {"element": 4, "name": "Defender One", "position": "DEF"},
            {"element": 5, "name": "Defender Two", "position": "DEF"},
            {"element": 6, "name": "Defender Three", "position": "DEF"},
            {"element": 7, "name": "Defender Four", "position": "DEF"},
            {"element": 8, "name": "Defender Five", "position": "DEF"},
            {"element": 9, "name": "Keeper", "position": "GK"},
            {"element": 10, "name": "Midfielder Three", "position": "MID"},
            {"element": 11, "name": "Midfielder Four", "position": "MID"},
        ],
        "captain": {"element": 2, "name": "Bruno Fernandes"},
        "vice_captain": {"element": 3, "name": "Martin Odegaard"},
        "bench": {
            "bench_gk": {"name": "Bench Keeper"},
            "outfield_autosub_priority": [
                {"name": "Bench One"},
                {"name": "Bench Two"},
                {"name": "Bench Three"},
            ],
        },
        "xi_base_xpts": 50.0,
        "captain_adjusted_xpts": 55.0,
    }


def test_pitch_contains_all_canonical_xi_players_and_four_bench_slots():
    body = render_s06_pitch(_content())
    for name in (
        "Haaland", "Bruno Fernandes", "Martin Odegaard", "Defender One",
        "Defender Two", "Defender Three", "Defender Four", "Defender Five",
        "Keeper", "Midfielder Three", "Midfielder Four", "Bench Keeper",
        "Bench One", "Bench Two", "Bench Three",
    ):
        assert name in body
    assert body.count('class="s06-bench-slot"') == 4
    assert 'class="s06-badge">C</span>' in body
    assert 'class="s06-badge">VC</span>' in body


def test_pitch_is_mobile_first_and_keeps_field_layers_in_fwd_to_gk_order():
    body = render_s06_pitch(_content())
    assert 'class="s06-pitch"' in body
    assert 'class="s06-field-markings"' in body
    assert "overflow-x" not in body
    assert body.index('s06-fwd"') < body.index('s06-mid"')
    assert body.index('s06-mid"') < body.index('s06-def"')
    assert body.index('s06-def"') < body.index('s06-gk"')
    assert "captain-adjusted xPts 55.0" in body


def test_pitch_contains_approved_mobile_visual_contract():
    body = render_s06_pitch(_content())
    assert "background:#063d29" in body
    assert "border:2px solid rgba(255,255,255,.78)" in body
    assert "background:#10252b" in body
    assert "@media(max-width:390px)" in body
    assert "max-width:430px" in body
