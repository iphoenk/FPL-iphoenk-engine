from __future__ import annotations

from src.engines import v4_full_universe_package_search_core as core
from src.engines.v4_full_universe_exact_batch import BatchContext, assert_scalar_equivalent, evaluate_batch
from src.engines.v4_wc_optimizer import Candidate


def _candidate(element: int, position: str, team: int, cost: int, base: float) -> Candidate:
    gw = tuple(round(base + index * 0.11, 4) for index in range(5))
    return Candidate(
        element=element,
        name=f"P{element}",
        position=position,
        team_id=team,
        team=f"T{team}",
        cost=cost,
        x3=round(base * 3.1, 4),
        x5=round(base * 5.2, 4),
        x10=round(base * 10.3, 4),
        x15=round(base * 15.4, 4),
        uncertainty=round(0.1 + (element % 7) * 0.013, 4),
        objective=round(base - 0.03, 4),
        gw_xpts=gw,
    )


def _squad() -> tuple[Candidate, ...]:
    rows = []
    element = 1
    spec = (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3))
    for position, count in spec:
        for index in range(count):
            rows.append(_candidate(element, position, 1 + ((element - 1) % 10), 40 + element, 1.0 + element * 0.07))
            element += 1
    return tuple(rows)


def _risk(players) -> dict[int, dict]:
    out = {}
    for player in players:
        seed = player.element % 11
        out[player.element] = {
            "projection_uncertainty": 0.05 + seed * 0.0111,
            "xmins_uncertainty": 0.08 + seed * 0.0097,
            "tactical_uncertainty": 0.07 + seed * 0.0073,
            "roster_change_uncertainty": 0.02 + seed * 0.0059,
            "price_risk": 0.10 + seed * 0.0123,
            "tactical_role_confidence": 0.55 + seed * 0.0177,
            "opponent_matchup_confidence": 0.50 + seed * 0.0161,
        }
    return out


def _context(current: tuple[Candidate, ...], outs: tuple[Candidate, ...], all_players) -> BatchContext:
    out_ids = {p.element for p in outs}
    keep = tuple(p for p in current if p.element not in out_ids)
    return BatchContext(
        outs=outs,
        keep=keep,
        baseline_metrics=core.reference._fast_metrics(current, include_detail=False),
        locked={"itb_tenths": 25, "free_transfers": 1},
        policy=core._policy(),
        risk_by_element=_risk(all_players),
    )


def test_exact_batch_matches_scalar_for_one_two_three_replacements():
    current = _squad()
    replacements = {
        "GK": [_candidate(101, "GK", 11, 45, 2.7), _candidate(102, "GK", 12, 47, 2.4)],
        "DEF": [_candidate(111, "DEF", 11, 49, 2.9), _candidate(112, "DEF", 12, 51, 3.0), _candidate(113, "DEF", 13, 46, 2.5)],
        "MID": [_candidate(121, "MID", 11, 61, 3.8), _candidate(122, "MID", 12, 58, 3.5), _candidate(123, "MID", 13, 55, 3.3)],
        "FWD": [_candidate(131, "FWD", 11, 65, 4.0), _candidate(132, "FWD", 12, 62, 3.7)],
    }
    all_players = current + tuple(p for rows in replacements.values() for p in rows)

    cases = [
        ((current[2],), [(replacements["DEF"][0],), (replacements["DEF"][1],)]),
        ((current[2], current[7]), [
            (replacements["DEF"][0], replacements["MID"][0]),
            (replacements["DEF"][1], replacements["MID"][1]),
        ]),
        ((current[2], current[7], current[12]), [
            (replacements["DEF"][0], replacements["MID"][0], replacements["FWD"][0]),
            (replacements["DEF"][1], replacements["MID"][1], replacements["FWD"][1]),
        ]),
    ]

    for outs, incoming_rows in cases:
        context = _context(current, outs, all_players)
        batch_rows = evaluate_batch(context, incoming_rows)
        assert_scalar_equivalent(context, incoming_rows, batch_rows)
