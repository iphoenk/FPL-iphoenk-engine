from src.engines.v12_integrated_report_runner import _rebind_s15b_competitive_scope


def test_s15b_competitive_scope_rebind_does_not_inherit_league_denominator():
    detail = {
        "denominator_scopes": {
            "LEAGUE": {"expected": 58, "collected": 58, "denominator": 58},
            "COMPETITIVE": {
                "label": "LEGACY_LEAGUE_SCOPE",
                "expected": 58,
                "collected": 58,
                "denominator": 58,
            },
        },
        "competitive_window": {
            "window_mode": "TOP10",
            "rival_count": 9,
            "standings_rival_count": 9,
            "picks_available_count": 8,
        },
    }

    out = _rebind_s15b_competitive_scope(detail)

    assert out["denominator_scopes"]["LEAGUE"]["denominator"] == 58
    assert out["denominator_scopes"]["COMPETITIVE"] == {
        "label": "COMPETITIVE_WINDOW",
        "definition": "TOP10",
        "expected": 9,
        "collected": 8,
        "denominator": 8,
        "includes_us": False,
        "coverage_pct": 88.9,
    }
