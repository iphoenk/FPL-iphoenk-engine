from __future__ import annotations

import unittest

from src.engines.v12_gw7_owner_midfield_mc import (
    MC_PATHS,
    OwnerMidfieldMCError,
    ROUTES,
    _verify_roster,
    evaluate,
)


OWN = [
    (572, 1, 11), (115, 2, 5), (8, 2, 1), (391, 2, 15),
    (426, 3, 16), (68, 3, 3), (40, 3, 6), (15, 3, 1),
    (124, 3, 5), (411, 4, 15), (165, 4, 6), (109, 1, 5),
    (346, 4, 13), (279, 2, 11), (31, 2, 1),
]
INCOMING = [(154, 3, 6), (12, 3, 1), (427, 3, 16)]


def _fake_inputs():
    players = [
        {"element": eid, "element_type": pos, "team": club}
        for eid, pos, club in OWN + INCOMING
    ]
    warm = {
        "schema": "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1",
        "planning_gw": 7,
        "report_slot": "2026-10-11T10:15:00+07:00",
        "owned": [{"element": eid} for eid, _, _ in OWN],
        "projections": {"planning_gw": 7, "players": players},
    }
    managers = [
        {"entry_id": 3462711 if rank == 5 else rank,
         "league_rank": rank,
         "league_total": 400 - rank}
        for rank in range(1, 59)
    ]
    picks = {
        "collected_manager_count": 58,
        "entries": {str(x["entry_id"]): {"picks": []} for x in managers},
    }
    standings = {"managers": managers}
    return warm, picks, standings


def _mock_optimizer(_projections, ids, *, planning_gw):
    assert len(ids) == 15
    goalkeepers = [x for x in ids if x in (572, 109)]
    bench = [goalkeepers[1], ids[2], ids[3], ids[4]]
    xi = [x for x in ids if x not in bench]
    return {
        "starting_xi": [{"element": x} for x in xi],
        "bench": {"gk": {"element": bench[0]},
                  "order": [{"element": x} for x in bench[1:]]},
        "captain": {"element": xi[0]},
        "vice_captain": {"element": xi[1]},
        "formation": "4-4-2",
        "formation_comparison": [
            {"formation": x} for x in
            ("3-4-3", "3-5-2", "4-3-3", "4-4-2",
             "4-5-1", "5-2-3", "5-3-2", "5-4-1")
        ],
    }


class GW7TwoMidOwnerMCContractTests(unittest.TestCase):
    def test_both_routes_are_distinct_and_canonical(self):
        warm, picks, standings = _fake_inputs()
        observed = {}

        def simulator(_projection, definitions, **kw):
            observed["args"] = kw
            observed["routes"] = definitions
            return {
                "execution_state": "EXECUTED",
                "canonical_pass": True,
                "actual_paths": MC_PATHS,
                "metrics": {name: {} for name in ROUTES},
                "pairwise": {},
                "convergence": {"status": "PASS"},
                "output_fingerprint": "f" * 64,
            }

        result = evaluate(
            warm, report_slot=warm["report_slot"],
            league_picks=picks, standings=standings,
            optimizer=_mock_optimizer, simulator=simulator,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(observed["args"]["actual_paths"], 500_000)
        self.assertTrue(observed["args"]["canonical"])
        self.assertEqual(observed["args"]["horizons"], (1, 3, 5))
        self.assertEqual(set(result["metrics"]), set(ROUTES))
        self.assertEqual(
            {r["route_id"]: r["execution_cost_points"] for r in observed["routes"]},
            {"HOLD": 0, "MBEUMO_ONLY": 0, "PALMER_MBEUMO": 4, "SAKA_MBEUMO": 4},
        )
        self.assertEqual(result["mini_league"]["competitive_rivals"], 9)
        self.assertIsNone(result["mini_league"]["probability_of_future_top3"])
        self.assertFalse(result["finance"]["route_decision_net_supported"])
        self.assertTrue(result["official_current15_unchanged"])

    def test_canonical_projection_team_id_is_numeric_and_team_label_is_text(self):
        warm, picks, standings = _fake_inputs()
        for row in warm["projections"]["players"]:
            row["team_id"] = row["team"]
            row["team"] = "Arsenal" if row["team_id"] == 1 else "Official team name"
        def simulator(_projection, definitions, **kw):
            return {
                "execution_state": "EXECUTED",
                "canonical_pass": True,
                "actual_paths": 500_000,
                "metrics": {k: {} for k in ROUTES},
                "paired_outputs": {"PALMER_MBEUMO__VS__SAKA_MBEUMO__H1": {"p_gt": 0.5}},
                "convergence_evidence": {"status": "PASS"},
                "output_fingerprint": "a" * 64,
            }
        result = evaluate(
            warm, report_slot=warm["report_slot"],
            league_picks=picks, standings=standings,
            optimizer=_mock_optimizer, simulator=simulator,
        )
        self.assertIn("PALMER_MBEUMO__VS__SAKA_MBEUMO__H1", result["pairwise"])
        self.assertEqual(result["convergence"]["status"], "PASS")
    def test_fails_closed_when_current_gw_or_occurrence_changes(self):
        warm, picks, standings = _fake_inputs()
        with self.assertRaises(OwnerMidfieldMCError):
            evaluate(
                {**warm, "planning_gw": 6}, report_slot=warm["report_slot"],
                league_picks=picks, standings=standings,
                optimizer=_mock_optimizer, simulator=lambda *_a, **_k: {},
            )
        with self.assertRaises(OwnerMidfieldMCError):
            evaluate(
                warm, report_slot="2026-10-11T10:30:00+07:00",
                league_picks=picks, standings=standings,
                optimizer=_mock_optimizer, simulator=lambda *_a, **_k: {},
            )

    def test_does_not_allow_four_arsenal_players(self):
        warm, _picks, _standings = _fake_inputs()
        pmap = {row["element"]: row for row in warm["projections"]["players"]}
        with self.assertRaises(OwnerMidfieldMCError):
            _verify_roster(
                [12 if x == 426 else x for x, _, _ in OWN],
                pmap,
            )

    def test_aborts_if_mc_not_500k_pass(self):
        warm, picks, standings = _fake_inputs()
        with self.assertRaises(OwnerMidfieldMCError):
            evaluate(
                warm, report_slot=warm["report_slot"],
                league_picks=picks, standings=standings,
                optimizer=_mock_optimizer,
                simulator=lambda *_a, **_k: {
                    "execution_state": "EXECUTED",
                    "canonical_pass": True,
                    "actual_paths": 200_000,
                },
            )


if __name__ == "__main__":
    unittest.main()
