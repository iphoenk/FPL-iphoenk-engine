from __future__ import annotations


def gw_value(player, index: int) -> float:
    """Return one projected-GW value, with a zero tail beyond available fixtures."""
    values = player.gw_xpts
    return values[index] if index < len(values) else 0.0
