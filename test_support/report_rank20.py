from __future__ import annotations


def rank20_rows(start: int, direction: str) -> list[dict]:
    """Return one schema-complete synthetic R2 RISE20/FALL20 fixture."""
    normalized = str(direction or "").strip().upper()
    if normalized not in {"RISE", "FALL"}:
        raise ValueError("direction must be RISE or FALL")
    sign = 1.0 if normalized == "RISE" else -1.0
    return [
        {
            "rank": index + 1,
            "element_id": start + index,
            "player_name": f"fixture-{normalized.lower()}-{index + 1:02d}",
            "current_price": round(5.0 + index / 10, 1),
            "ownership_percent": float(index + 1),
            "ownership_tag": "NON_OWNED",
            "direction": normalized,
            "current_progress_percent": sign * 70.0,
            "projection_offset_0_percent": sign * 95.0,
            "predicted_change_cycle": "NEXT_UPDATE",
            "predicted_change_at": "2026-09-17T06:00:00+07:00",
            "eta_human": "next price cycle",
            "model_urgency": "HIGH",
            "confidence": "HIGH",
            "source": "TEST_FIXTURE",
            "observed_at": "2026-09-16T20:00:00+07:00",
            "raw_payload_hash": "a" * 64,
        }
        for index in range(20)
    ]
