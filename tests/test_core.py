from src.engines.team_value import sell_cost
from src.models.package_optimizer_v2 import legal_squad
from src.rules import GOAL_POINTS


def test_sell_value():
    assert sell_cost(78, 75) == 76
    assert sell_cost(74, 75) == 74
    assert sell_cost(75, 75) == 75


def test_legal_counts_via_canonical_package_optimizer():
    players = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            players.append({"element": element, "position": position, "team_id": element})
            element += 1
    assert legal_squad(players)


def test_goalkeeper_goal_rule_is_ten_points():
    assert GOAL_POINTS[1] == 10
