from __future__ import annotations

from src.engines.fpl_rules_2026 import POSITION_COUNTS
from src.utils import CONFIG, read_json


POLICY = CONFIG / "serving_improvement_registry.json"


def watchlist_position_counts() -> dict[str, int]:
    """Return the governed watchlist cardinality from its single registry owner."""
    policy = (read_json(POLICY, {}) or {}).get("watchlist") or {}
    exact = int(policy.get("exact_per_position") or 0)
    positions = [str(position) for position in (policy.get("positions") or [])]
    if exact <= 0 or not positions or len(set(positions)) != len(positions):
        raise RuntimeError("invalid governed watchlist policy")
    invalid = [position for position in positions if position not in POSITION_COUNTS]
    if invalid:
        raise RuntimeError(f"invalid governed watchlist positions: {invalid}")
    if policy.get("exclude_owned") is not True:
        raise RuntimeError("governed watchlist policy must exclude owned players")
    return {position: exact for position in positions}
