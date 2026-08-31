from __future__ import annotations

from copy import deepcopy

from src.engines.p0_decision_quality import projection_signature
from src.models.official_role_evidence import ROLE_SOURCE, attach_official_role_evidence


def _projections() -> dict:
    return {
        "players": [
            {
                "element": 10,
                "name": "Alpha",
                "xpts_by_gw": [{"gw": 3, "mean": 5.25}],
            },
            {
                "element": 20,
                "name": "Beta",
                "xpts_by_gw": [{"gw": 3, "mean": 4.1}],
            },
        ]
    }


def test_official_rank_fields_become_advisory_role_evidence_without_share_inference():
    projections = _projections()
    before = projection_signature(deepcopy(projections))
    bootstrap = {
        "elements": [
            {
                "id": 10,
                "corners_and_indirect_freekicks_order": 1,
                "corners_and_indirect_freekicks_text": "Primary corners",
                "direct_freekicks_order": 2,
                "direct_freekicks_text": "Second direct free-kick option",
                "penalties_order": 1,
                "penalties_text": "Primary penalties",
            },
            {"id": 20},
        ]
    }

    summary = attach_official_role_evidence(projections, bootstrap)
    alpha = projections["players"][0]
    beta = projections["players"][1]

    assert projection_signature(projections) == before
    assert alpha["set_piece_role"]["source"] == ROLE_SOURCE
    assert alpha["set_piece_role"]["corners_and_indirect_freekicks_order"] == 1
    assert alpha["set_piece_role"]["direct_freekicks_order"] == 2
    assert alpha["set_piece_role"]["share_or_probability_inferred"] is False
    assert "share" not in alpha["set_piece_role"]
    assert "probability" not in alpha["set_piece_role"]
    assert alpha["penalty_role"]["order"] == 1
    assert alpha["penalty_role"]["share_or_probability_inferred"] is False
    assert "set_piece_role" not in beta
    assert "penalty_role" not in beta
    assert summary["set_piece_role_players"] == 1
    assert summary["penalty_role_players"] == 1
    assert summary["direct_xpts_mutation"] is False
    assert summary["direct_xmins_mutation"] is False


def test_missing_or_nonpositive_orders_do_not_fabricate_role_evidence():
    projections = _projections()
    bootstrap = {
        "elements": [
            {
                "id": 10,
                "corners_and_indirect_freekicks_order": 0,
                "direct_freekicks_order": -1,
                "penalties_order": None,
                "corners_and_indirect_freekicks_text": "",
                "direct_freekicks_text": None,
                "penalties_text": "",
            },
            {"id": 20},
        ]
    }

    summary = attach_official_role_evidence(projections, bootstrap)

    assert all("set_piece_role" not in row for row in projections["players"])
    assert all("penalty_role" not in row for row in projections["players"])
    assert summary["players_with_any_role_evidence"] == 0
    assert summary["missing_role_evidence_remains_missing"] is True


def test_explicit_official_text_is_retained_even_when_rank_is_unavailable():
    projections = _projections()
    bootstrap = {
        "elements": [
            {
                "id": 10,
                "penalties_order": None,
                "penalties_text": "Listed penalty taker",
            }
        ]
    }

    attach_official_role_evidence(projections, bootstrap)
    role = projections["players"][0]["penalty_role"]
    assert role["text"] == "Listed penalty taker"
    assert role["official_rank_available"] is False
    assert role["source"] == ROLE_SOURCE
