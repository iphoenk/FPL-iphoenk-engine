from pathlib import Path


def test_exhaustive_finalizer_has_no_watchlist_or_player_target_seed():
    text = Path("src/engines/package_optimizer_exhaustive_finalize.py").read_text(encoding="utf-8")
    assert "dss_watchlist" not in text
    assert "watchlist.json" not in text
    for name in ("Mbeumo", "Cherki", "Foden", "Schade", "Barry", "Guehi", "Guéhi"):
        assert name not in text
