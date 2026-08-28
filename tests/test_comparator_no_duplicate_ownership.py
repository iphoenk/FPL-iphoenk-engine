from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_comparator_reuses_declared_shared_primitives_and_owns_only_orchestration():
    registry = json.loads((ROOT / "config" / "v3_architecture_ownership_registry.json").read_text())
    comparator_rows = [row for row in registry["responsibilities"] if row["id"] == "OWNED_CHALLENGER_COMPARISON"]
    assert comparator_rows == [{
        "id": "OWNED_CHALLENGER_COMPARISON",
        "owner_service": "watchlist",
        "implementation": "src.engines.owned_challenger_comparator",
    }]
    shared = {row["id"]: row for row in registry["shared_primitives"]}
    for primitive in (
        "XMINS_DISTRIBUTION",
        "ADVANCED_ATTACKING_EVIDENCE",
        "TACTICAL_MATCHUP_CONTEXT",
        "TEAM_STRENGTH_AND_FIXTURE_PROBABILITY",
        "MULTI_HORIZON_PROJECTION",
        "PACKAGE_SCORING_AND_LEGALITY_PRECHECK",
        "PRICE_MARKET_EVIDENCE",
    ):
        assert "watchlist" in shared[primitive]["consumers"]
        assert shared[primitive]["owner"] != "watchlist" or primitive == "TACTICAL_DECISION_CONSUMPTION"
