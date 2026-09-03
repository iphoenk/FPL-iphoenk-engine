from __future__ import annotations

from src.engines.v4_full_universe_package_search import safe_prune_incoming_players
from src.engines.v4_wc_optimizer import Candidate


def _candidate(element: int, *, team_id: int = 1, cost: int = 50, x5: float = 20.0, name: str | None = None) -> Candidate:
    per_gw = x5 / 5.0
    return Candidate(
        element=element,
        name=name or f"P{element}",
        position="MID",
        team_id=team_id,
        team=f"T{team_id}",
        cost=cost,
        x3=per_gw * 3,
        x5=x5,
        x10=per_gw * 10,
        x15=per_gw * 15,
        uncertainty=0.1,
        objective=per_gw,
        gw_xpts=(per_gw,) * 15,
    )


def _prediction(player: Candidate, *, start: float = 0.9, dnp: float = 0.05, role_prior: float = 0.5) -> dict:
    return {
        "element": player.element,
        "xpts_3": player.x3,
        "xpts_5": player.x5,
        "xpts_10": player.x10,
        "xpts_15": player.x15,
        "uncertainty": player.uncertainty,
        "priors": {"role_prior": role_prior, "xg90_prior": 0.2, "xa90_prior": 0.2},
        "fixtures": [
            {
                "xmins": {
                    "start_probability": start,
                    "dnp_probability": dnp,
                    "start_probability_confidence": 0.9,
                },
                "rates": {
                    "raw_xg90": 0.2,
                    "raw_xa90": 0.2,
                    "current_season_weight": 0.5,
                },
            }
            for _ in range(5)
        ],
    }


def _universe(player: Candidate) -> dict:
    return {
        "element": player.element,
        "name": player.name,
        "team": player.team,
        "team_id": player.team_id,
        "position": player.position,
        "ownership": "10.0",
        "transfers_in_event": 1000,
        "transfers_out_event": 100,
    }


def _interaction(player: Candidate, *, xmins_uncertainty: float = 0.1, tactical_uncertainty: float = 0.1, role_confidence: float = 0.8, opponent_confidence: float = 0.8, roster_uncertainty: float = 0.0) -> dict:
    return {
        "element": player.element,
        "xmins": {"uncertainty": xmins_uncertainty},
        "tactical_interaction": {"tactical_uncertainty": tactical_uncertainty},
        "roster_change": {"roster_change_uncertainty": roster_uncertainty},
        "confidence_dimensions": {
            "player_role_confidence": role_confidence,
            "Understat_confidence": opponent_confidence,
        },
    }


def _price(player: Candidate, *, urgency: str = "LOW", projections: list[dict] | None = None) -> dict:
    return {
        "element_id": player.element,
        "current_price": player.cost / 10.0,
        "model_urgency": urgency,
        "direction": "RISE",
        "official_projections": projections or [],
        "raw": {"now_cost": player.cost},
    }


def _context(players: list[Candidate], interactions: dict[int, dict] | None = None, prices: list[dict] | None = None):
    return {
        "interactions": {"players": {str(p.element): (interactions or {}).get(p.element, _interaction(p)) for p in players}},
        "prices": {"players": prices or [_price(p) for p in players]},
        "predictions": {"players": [_prediction(p) for p in players]},
        "universe": {"players": [_universe(p) for p in players]},
    }


def test_xpts_advantage_cannot_prune_safer_xmins_candidate():
    stronger_xpts = _candidate(101, x5=25.0)
    safer_minutes = _candidate(102, x5=20.0)
    ctx = _context(
        [stronger_xpts, safer_minutes],
        interactions={
            101: _interaction(stronger_xpts, xmins_uncertainty=0.8),
            102: _interaction(safer_minutes, xmins_uncertainty=0.1),
        },
    )
    kept, proofs = safe_prune_incoming_players([stronger_xpts, safer_minutes], set(), **ctx)
    assert {row.element for row in kept} == {101, 102}
    assert proofs == []


def test_full_decision_dominator_may_prune_same_team_same_position_candidate():
    dominator = _candidate(201, cost=45, x5=25.0)
    dominated = _candidate(202, cost=50, x5=20.0)
    ctx = _context([dominator, dominated])
    kept, proofs = safe_prune_incoming_players([dominator, dominated], set(), **ctx)
    assert [row.element for row in kept] == [201]
    assert len(proofs) == 1
    proof = proofs[0]
    assert proof["pruned_element"] == 202
    assert proof["dominating_element"] == 201
    assert proof["safe_legality_equivalence"] is True
    assert proof["safe_package_frontier_equivalence"] is True
    assert proof["safe_projected_affordability_equivalence"] is True
    assert proof["safe_recommendation_sanity_equivalence"] is True
    assert "xmins_uncertainty" in proof["minimize_dimensions"]
    assert "projected_buy_cost_2" in proof["minimize_dimensions"]
    assert "sanity_confidence" in proof["maximize_dimensions"]


def test_future_price_feasibility_blocks_unsafe_pruning():
    future_riser = _candidate(301, cost=50, x5=25.0)
    stable = _candidate(302, cost=50, x5=20.0)
    prices = [
        _price(
            future_riser,
            projections=[
                {"offset": 0, "projected_percent": 101.0},
                {"offset": 1, "projected_percent": 105.0},
                {"offset": 2, "projected_percent": 110.0},
            ],
        ),
        _price(stable),
    ]
    ctx = _context([future_riser, stable], prices=prices)
    kept, proofs = safe_prune_incoming_players([future_riser, stable], set(), **ctx)
    assert {row.element for row in kept} == {301, 302}
    assert proofs == []


def test_cross_team_player_is_never_pruned_by_different_club_dominator():
    left = _candidate(401, team_id=1, cost=45, x5=30.0)
    right = _candidate(402, team_id=2, cost=50, x5=20.0)
    ctx = _context([left, right])
    kept, proofs = safe_prune_incoming_players([left, right], set(), **ctx)
    assert {row.element for row in kept} == {401, 402}
    assert proofs == []


def test_player_names_do_not_participate_in_pruning_authority():
    left = _candidate(501, cost=45, x5=25.0, name="Benchmark Target A")
    right = _candidate(502, cost=50, x5=20.0, name="Ordinary Player")
    ctx = _context([left, right])
    kept_a, proofs_a = safe_prune_incoming_players([left, right], set(), **ctx)

    left_renamed = _candidate(501, cost=45, x5=25.0, name="Ordinary Player")
    right_renamed = _candidate(502, cost=50, x5=20.0, name="Benchmark Target A")
    ctx_renamed = _context([left_renamed, right_renamed])
    kept_b, proofs_b = safe_prune_incoming_players([left_renamed, right_renamed], set(), **ctx_renamed)

    assert [row.element for row in kept_a] == [row.element for row in kept_b] == [501]
    assert [(p["dominating_element"], p["pruned_element"]) for p in proofs_a] == [(501, 502)]
    assert [(p["dominating_element"], p["pruned_element"]) for p in proofs_b] == [(501, 502)]
