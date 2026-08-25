from src.engines.team_value import sell_cost
from src.models.optimizer import legal_counts
from src.models.projection import project_points


def test_sell_value():
    assert sell_cost(78,75)==76
    assert sell_cost(74,75)==74
    assert sell_cost(75,75)==75


def test_legal_counts():
    players=[]
    for i in range(2):players.append({"position":"GK","team":i})
    for i in range(5):players.append({"position":"DEF","team":10+i})
    for i in range(5):players.append({"position":"MID","team":20+i})
    for i in range(3):players.append({"position":"FWD","team":30+i})
    assert legal_counts(players)


def test_goalkeeper_goal_is_worth_ten_points():
    player={"element_type":1,"status":"a","minutes":90,"starts":1,"saves":0}
    common={
        "start_probability":1.0,
        "xa_per90":0.0,
        "clean_sheet_probability":0.0,
        "saves_per90":0.0,
        "defcon_points_per90":0.0,
        "bonus_per90":0.0,
    }
    without_goal=project_points(player,{**common,"xg_per90":0.0})
    with_one_expected_goal=project_points(player,{**common,"xg_per90":1.0})
    assert with_one_expected_goal["components"]["attack"]-without_goal["components"]["attack"]==10.0
