from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V12_NATIVE_PATHS = (
    "src/engines/v12_player_minutes.py",
    "src/engines/v12_player_events.py",
    "src/engines/v12_package_search.py",
    "src/engines/v12_package_utility.py",
    "src/engines/v12_model_evidence.py",
    "src/engines/v12_monte_carlo.py",
    "src/engines/v12_tactical_role.py",
    "src/engines/v12_lineup_optimizer.py",
    "src/engines/v12_mini_league_overlay.py",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "src.runtime_v3",
    "src.runtime_v4",
    "src.runtime_v5",
)


def _import_targets(source: str) -> set[str]:
    tree = ast.parse(source)
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def test_active_native_p1_modules_have_zero_legacy_runtime_imports():
    for rel_path in V12_NATIVE_PATHS:
        path = ROOT / rel_path
        assert path.is_file(), rel_path
        imports = _import_targets(path.read_text(encoding="utf-8"))
        forbidden = sorted(
            target
            for target in imports
            if target.startswith(FORBIDDEN_IMPORT_PREFIXES)
        )
        assert forbidden == [], f"{rel_path} imports legacy runtime: {forbidden}"


def test_active_native_p1_surface_is_complete():
    assert set(V12_NATIVE_PATHS) == {
        "src/engines/v12_player_minutes.py",
        "src/engines/v12_player_events.py",
        "src/engines/v12_package_search.py",
        "src/engines/v12_package_utility.py",
        "src/engines/v12_model_evidence.py",
        "src/engines/v12_monte_carlo.py",
        "src/engines/v12_tactical_role.py",
        "src/engines/v12_lineup_optimizer.py",
        "src/engines/v12_mini_league_overlay.py",
    }
