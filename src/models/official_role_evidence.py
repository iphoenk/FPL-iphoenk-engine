from __future__ import annotations

from typing import Any


ROLE_SOURCE = "OFFICIAL_FPL_BOOTSTRAP"


def _positive_rank(value: Any) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _set_piece_role(player: dict[str, Any]) -> dict[str, Any] | None:
    corners_rank = _positive_rank(player.get("corners_and_indirect_freekicks_order"))
    direct_rank = _positive_rank(player.get("direct_freekicks_order"))
    corners_text = _text(player.get("corners_and_indirect_freekicks_text"))
    direct_text = _text(player.get("direct_freekicks_text"))
    if corners_rank is None and direct_rank is None and corners_text is None and direct_text is None:
        return None
    return {
        "source": ROLE_SOURCE,
        "corners_and_indirect_freekicks_order": corners_rank,
        "corners_and_indirect_freekicks_text": corners_text,
        "direct_freekicks_order": direct_rank,
        "direct_freekicks_text": direct_text,
        "official_rank_available": corners_rank is not None or direct_rank is not None,
        "advisory_only": True,
        "share_or_probability_inferred": False,
    }


def _penalty_role(player: dict[str, Any]) -> dict[str, Any] | None:
    rank = _positive_rank(player.get("penalties_order"))
    text = _text(player.get("penalties_text"))
    if rank is None and text is None:
        return None
    return {
        "source": ROLE_SOURCE,
        "order": rank,
        "text": text,
        "official_rank_available": rank is not None,
        "advisory_only": True,
        "share_or_probability_inferred": False,
    }


def attach_official_role_evidence(projections: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    official_players = {
        int(player.get("id")): player
        for player in bootstrap.get("elements") or []
        if player.get("id") is not None
    }
    set_piece_players = 0
    penalty_players = 0
    annotated_players = 0

    for projection in projections.get("players") or []:
        try:
            element = int(projection.get("element"))
        except (TypeError, ValueError):
            continue
        official = official_players.get(element)
        if not isinstance(official, dict):
            projection.pop("set_piece_role", None)
            projection.pop("penalty_role", None)
            continue

        set_piece = _set_piece_role(official)
        penalty = _penalty_role(official)
        if set_piece is not None:
            projection["set_piece_role"] = set_piece
            set_piece_players += 1
        else:
            projection.pop("set_piece_role", None)
        if penalty is not None:
            projection["penalty_role"] = penalty
            penalty_players += 1
        else:
            projection.pop("penalty_role", None)
        annotated_players += int(set_piece is not None or penalty is not None)

    summary = {
        "source": ROLE_SOURCE,
        "set_piece_role_players": set_piece_players,
        "penalty_role_players": penalty_players,
        "players_with_any_role_evidence": annotated_players,
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
        "share_or_probability_inference_forbidden": True,
        "missing_role_evidence_remains_missing": True,
    }
    projections["official_role_evidence"] = summary
    return summary
