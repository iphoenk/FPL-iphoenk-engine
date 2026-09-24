from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Mapping

SOURCE_CLASS = "MANUAL_CAPTURE_CURRENT"
SCHEMA_VERSION = "1.0"


class ManualIdentityError(ValueError):
    pass


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ManualIdentityError(f"{field}:boolean_not_allowed")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ManualIdentityError(f"{field}:integer_required") from exc


def decode_manual_identity_b64(raw: str, *, planning_gw: int) -> dict[str, Any]:
    """Decode and validate a human-captured current-team identity.

    The payload is evidence, not an FPL credential. Purchase price is optional:
    a screen that does not prove it must not invent it.
    """
    if not str(raw or "").strip():
        raise ManualIdentityError("empty_payload")
    try:
        decoded = base64.b64decode(str(raw).strip(), validate=True)
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualIdentityError("invalid_base64_json") from exc
    if not isinstance(payload, Mapping):
        raise ManualIdentityError("object_required")

    if str(payload.get("schema_version")) != SCHEMA_VERSION:
        raise ManualIdentityError("unsupported_schema_version")
    if str(payload.get("source_class") or "").upper() != SOURCE_CLASS:
        raise ManualIdentityError("source_class_mismatch")
    gw = _int(payload.get("gw"), "gw")
    if gw != int(planning_gw):
        raise ManualIdentityError("planning_gw_mismatch")
    if not payload.get("captured_at"):
        raise ManualIdentityError("captured_at_required")

    raw_players = payload.get("players")
    if not isinstance(raw_players, list) or len(raw_players) != 15:
        raise ManualIdentityError("exactly_15_players_required")
    players: list[dict[str, Any]] = []
    seen: set[int] = set()
    positions = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for index, row in enumerate(raw_players):
        if not isinstance(row, Mapping):
            raise ManualIdentityError(f"players[{index}]:object_required")
        element = _int(row.get("element_id"), f"players[{index}].element_id")
        if element <= 0 or element in seen:
            raise ManualIdentityError("duplicate_or_invalid_element_id")
        seen.add(element)
        position = str(row.get("position") or "").upper()
        if position not in positions:
            raise ManualIdentityError(f"players[{index}].position_invalid")
        positions[position] += 1
        normalized = {"element_id": element, "position": position}
        for field in ("current_price", "selling_price", "purchase_price"):
            if row.get(field) is not None:
                normalized[field] = _int(row.get(field), f"players[{index}].{field}")
        players.append(normalized)
    if positions != {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}:
        raise ManualIdentityError("invalid_position_shape")

    bank = _int(payload.get("bank"), "bank")
    free_transfers = _int(payload.get("free_transfers"), "free_transfers")
    transfer_cost = _int(payload.get("transfer_cost", 0), "transfer_cost")
    if min(bank, free_transfers, transfer_cost) < 0:
        raise ManualIdentityError("negative_finance_value")

    chips = payload.get("chips")
    if not isinstance(chips, Mapping):
        raise ManualIdentityError("chips_object_required")

    return {
        "schema_version": SCHEMA_VERSION,
        "source_class": SOURCE_CLASS,
        "gw": gw,
        "generated_at": str(payload["captured_at"]),
        "bank": bank,
        "free_transfers": free_transfers,
        "hit_cost": transfer_cost,
        "chips": dict(chips),
        "players": players,
        "availability": {
            "bank": "AVAILABLE",
            "free_transfers": "AVAILABLE",
            "chips": "AVAILABLE",
            "purchase_price": (
                "AVAILABLE" if all("purchase_price" in p for p in players)
                else "UNAVAILABLE"
            ),
            "selling_price": (
                "AVAILABLE" if all("selling_price" in p for p in players)
                else "UNAVAILABLE"
            ),
        },
        "governance": {
            "manual_capture": True,
            "credential": False,
            "purchase_price_must_be_evidenced": True,
        },
    }
