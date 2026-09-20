from __future__ import annotations

import json
from pathlib import Path

from src.platform.legacy_execution_isolation_validate import (
    CANONICAL_PATH,
    STATE_PATH,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]


def test_active_execution_graph_has_zero_legacy_execution():
    assert validate(ROOT) == []


def test_active_workflow_tree_contains_no_versioned_legacy_workflow():
    names = {
        path.name
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    }
    assert not any(name.startswith(("v3-", "v4-", "v5-")) for name in names)


def test_v12_authority_and_state_semantics_are_exact():
    assert (ROOT / CANONICAL_PATH).is_file()
    state = json.loads((ROOT / STATE_PATH).read_text(encoding="utf-8"))
    assert state["architecture_authority"] == CANONICAL_PATH
    assert state["authority"] is False
    assert state["non_authoritative_state_file"] is True
    assert state["latest_explicit_user_state_wins"] is True
    assert state["core_policy"]["v6_only"] is True
    assert state["core_policy"]["v3_v4_v5_fallback_allowed"] is False
