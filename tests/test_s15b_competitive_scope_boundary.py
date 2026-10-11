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



def test_s15b_deep_assembly_has_competitive_rebind_before_rendering():
    """Guard the active DEEP path, not only the MINI_LEAGUE_ONLY path."""
    from pathlib import Path

    source = Path("src/engines/v12_integrated_report_runner.py").read_text(
        encoding="utf-8"
    )
    deep_anchor = "mini_deep_detail = _rebind_s15b_competitive_scope(mini_deep_detail)"
    assert source.count(deep_anchor) >= 2
    assert "**mini_deep_detail," in source
    assert "**s15b_detail," in source



def test_competitive_cohort_preserves_tied_standings_positions():
    from src.engines.v12_integrated_report_runner import _select_competitive_rows

    ordered = [
        {"entry_id": 1, "league_rank": 1},
        {"entry_id": 2, "league_rank": 2},
        {"entry_id": 3, "league_rank": 7},
        {"entry_id": 4, "league_rank": 7},
        {"entry_id": 5, "league_rank": 9},
        {"entry_id": 6, "league_rank": 10},
        {"entry_id": 7, "league_rank": 11},
        {"entry_id": 8, "league_rank": 12},
        {"entry_id": 9, "league_rank": 13},
        {"entry_id": 10, "league_rank": 14},
    ]

    out = _select_competitive_rows(
        ordered,
        our_entry_id=3,
        competitive_window={"window_mode": "TOP10", "rival_count": 9},
    )

    assert len(out) == 9
    assert 3 not in {row["entry_id"] for row in out}
    assert 4 in {row["entry_id"] for row in out}
