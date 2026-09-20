from __future__ import annotations

from pathlib import Path

from src.engines import (
    v12_lineup_optimizer,
    v12_mini_league_overlay,
    v12_model_evidence,
    v12_monte_carlo,
    v12_package_search,
    v12_package_utility,
    v12_player_events,
    v12_player_minutes,
    v12_tactical_role,
)


V12_NATIVE_MODULES = (
    v12_player_minutes,
    v12_player_events,
    v12_package_search,
    v12_package_utility,
    v12_model_evidence,
    v12_monte_carlo,
    v12_tactical_role,
    v12_lineup_optimizer,
    v12_mini_league_overlay,
)

FORBIDDEN_RUNTIME_TOKENS = (
    "src.runtime_v3",
    "src.runtime_v4",
    "src.runtime_v5",
    "runtime_v3",
    "runtime_v4",
    "runtime_v5",
)


def test_v12_native_p1_modules_have_zero_legacy_runtime_imports():
    for module in V12_NATIVE_MODULES:
        path = Path(module.__file__)
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            assert token not in source, f"{path.name} contains forbidden legacy runtime token {token}"


def test_v12_native_p1_surface_is_importable_without_legacy_runtime():
    names = {module.__name__ for module in V12_NATIVE_MODULES}
    assert names == {
        "src.engines.v12_player_minutes",
        "src.engines.v12_player_events",
        "src.engines.v12_package_search",
        "src.engines.v12_package_utility",
        "src.engines.v12_model_evidence",
        "src.engines.v12_monte_carlo",
        "src.engines.v12_tactical_role",
        "src.engines.v12_lineup_optimizer",
        "src.engines.v12_mini_league_overlay",
    }
