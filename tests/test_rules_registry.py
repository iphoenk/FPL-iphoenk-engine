from __future__ import annotations

from src.engines.rules_compliance_audit import audit
from src.engines.team_value import sell_cost
from src.models.package_optimizer_v2 import legal_squad
from src.rules import (
    ACTIVE_RULESET,
    LINEUP_RULES,
    RULESET_ID,
    RULESET_SEASON,
    RULES_MANIFEST,
    SQUAD_RULES,
    active_ruleset_fingerprint,
    load_active_ruleset,
)


def test_active_ruleset_manifest_and_fingerprint():
    rules = load_active_ruleset()
    assert RULESET_ID == "FPL_2026_27"
    assert RULESET_SEASON == "2026/27"
    assert RULES_MANIFEST["active_ruleset"] == RULESET_ID
    assert rules["ruleset_id"] == RULESET_ID
    assert len(active_ruleset_fingerprint()) == 64


def test_rules_registry_is_single_source_for_squad_and_lineup_constraints():
    assert SQUAD_RULES["squad_size"] == 15
    assert SQUAD_RULES["position_counts"] == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert SQUAD_RULES["max_players_per_club"] == 3
    assert LINEUP_RULES["starting_xi_size"] == 11
    assert "3-4-3" in LINEUP_RULES["legal_formations"]


def test_sell_value_uses_declared_registry_method():
    assert ACTIVE_RULESET["finance"]["sell_value"]["method"] == "official_half_profit_floor"
    assert sell_cost(50, 50) == 50
    assert sell_cost(49, 50) == 49
    assert sell_cost(51, 50) == 50
    assert sell_cost(52, 50) == 51
    assert sell_cost(55, 50) == 52


def test_optimizer_legality_reads_active_ruleset():
    players = []
    team = 1
    element = 1
    for position, count in SQUAD_RULES["position_counts"].items():
        for _ in range(count):
            players.append({"element": element, "position": position, "team_id": team})
            element += 1
            team = team + 1 if team < 5 else 1
    assert legal_squad(players) is True


def test_rules_compliance_structural_audit_passes_without_remote_mutation():
    result = audit(check_remote=False)
    assert result["overall"] == "PASS"
    assert result["registry_integrity"]["status"] == "PASS"
    assert result["drift"]["status"] == "NOT_RUN"
    assert result["governance"]["remote_change_never_auto_mutates_rules"] is True
    assert result["governance"]["registry_integrity_failure_blocks_go"] is True
