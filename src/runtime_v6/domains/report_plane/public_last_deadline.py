from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SOURCE = "PUBLIC_LAST_DEADLINE"


class PublicIdentityGap(RuntimeError):
    """Raised when public evidence cannot prove an identity field exactly."""


def selling_price_tenths(*, purchase_price: int, current_price: int) -> int:
    """Official FPL sale rule using integer tenths only."""
    purchase = int(purchase_price)
    current = int(current_price)
    if current >= purchase:
        return purchase + (current - purchase) // 2
    return current


def purchase_prices_from_transfer_history(
    *,
    last_deadline_elements: list[int],
    transfer_history: list[dict[str, Any]],
    initial_purchase_prices: dict[int, int] | None = None,
) -> dict[int, int]:
    """Replay public transfers to recover acquisition prices.

    Public transfer history proves element_in_cost for transferred-in players.
    Initial-squad acquisition prices are deliberately NOT inferred. They must
    be supplied by independently authoritative evidence.
    """
    acquired = {int(k): int(v) for k, v in (initial_purchase_prices or {}).items()}
    for row in sorted(
        (row for row in transfer_history if isinstance(row, dict)),
        key=lambda row: str(row.get("time") or ""),
    ):
        if row.get("element_out") is not None:
            acquired.pop(int(row["element_out"]), None)
        if row.get("element_in") is not None and row.get("element_in_cost") is not None:
            acquired[int(row["element_in"])] = int(row["element_in_cost"])

    missing = sorted(set(map(int, last_deadline_elements)) - set(acquired))
    if missing:
        raise PublicIdentityGap(
            "initial_or_unproven_purchase_price:" + ",".join(map(str, missing))
        )
    return {element: acquired[element] for element in map(int, last_deadline_elements)}


def public_last_deadline_eligible(*, reconstruction_valid: bool, pending_transfers: str) -> bool:
    if pending_transfers not in {"none", "present"}:
        raise ValueError("PENDING_TRANSFERS must be exactly 'none' or 'present'")
    return bool(reconstruction_valid) and pending_transfers == "none"
