"""Regression: full mini-league ownership is a ninth, fact-bound DEEP S15B table."""
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines
from src.engines.v12_deep_presentation_lock import load_deep_presentation_lock


def _row(player: str, position: str, owned: int, xi: int, bench: int, captain: int, vice: int, eo: int) -> dict:
    return {
        "player": player, "position": position, "denominator": 58,
        "ownership_count": owned, "ownership_pct": round(owned / 58 * 100, 1),
        "starter_count": xi, "starter_pct": round(xi / 58 * 100, 1),
        "bench_count": bench, "bench_pct": round(bench / 58 * 100, 1),
        "captain_count": captain, "captain_pct": round(captain / 58 * 100, 1),
        "vice_count": vice, "vice_pct": round(vice / 58 * 100, 1),
        "effective_multiplier_sum": eo, "eo_pct": round(eo / 58 * 100, 1),
        "eo_supported": True,
    }


def test_full_league_ownership_render_sorted_and_complete():
    payload = {
        "coverage_state": "FULL",
        "expected_manager_count": 58,
        "submitted_picks_available_count": 58,
        "denominator_scopes": {
            "LEAGUE": {"denominator": 58, "expected": 58, "collected": 58},
            "RIVALS": {"denominator": 57, "expected": 57, "collected": 57},
            "COMPETITIVE": {"denominator": 9, "expected": 9, "collected": 9},
        },
        "league_full_composition": [
            _row("Palmer", "MID", 10, 10, 0, 1, 4, 11),
            _row("Haaland", "FWD", 43, 43, 0, 24, 7, 67),
        ],
        "league_unique_player_count": 2,
    }
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S15B", content=payload, owned_ids=set(), owned_names={}
    )
    text = "\n".join(lines)
    assert "### ALL LEAGUE PLAYER OWNERSHIP" in text
    assert "| Player | Pos | Owned | Ownership | Starter | Bench | Captain | Vice | EO |" in text
    assert "43/58 (74.1%)" in text
    assert "67/58 (115.5%)" in text
    assert text.index("| Haaland | FWD |") < text.index("| Palmer | MID |")
    assert "### OUR15 LEAGUE" in text
    assert "### OUR15 COMPETITIVE WINDOW" in text


def test_s15b_lock_contains_nine_independent_tables():
    tables = load_deep_presentation_lock()["sections"]["S15B"]["tables"]
    assert len(tables) == 9
    assert tables[2]["name"] == "All league player ownership"
    assert tables[2]["columns"] == [
        "Player", "Pos", "Owned", "Ownership", "Starter", "Bench",
        "Captain", "Vice", "EO",
    ]
