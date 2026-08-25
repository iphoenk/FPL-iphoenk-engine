from src.engines.fpl_rules_2026 import SCORING, DEFCON, chip_allowed, positional_defcon_actions
from src.models.v4_prediction import defcon_expected_points

def test_scoring_constants_2026_27():
    assert SCORING['goal_points'] == {'GK':10,'DEF':6,'MID':5,'FWD':4}
    assert SCORING['assist'] == 3
    assert SCORING['clean_sheet']['GK'] == 4 and SCORING['clean_sheet']['MID'] == 1
    assert SCORING['saves_per_point'] == 3 and SCORING['penalty_save'] == 5
    assert SCORING['yellow_card'] == -1 and SCORING['red_card'] == -3

def test_gk_never_gets_defcon():
    assert DEFCON['GK']['eligible'] is False
    assert defcon_expected_points(100,90,1,1.0) == 0.0

def test_def_uses_cbit_without_recoveries():
    assert DEFCON['DEF']['metric'] == 'CBIT' and DEFCON['DEF']['threshold'] == 10
    assert positional_defcon_actions('DEF',2,2,2,2,50) == 8

def test_mid_fwd_use_cbirt_with_recoveries():
    assert DEFCON['MID']['metric'] == 'CBIRT' and DEFCON['MID']['threshold'] == 12
    assert DEFCON['FWD']['metric'] == 'CBIRT' and DEFCON['FWD']['threshold'] == 12
    assert positional_defcon_actions('MID',2,2,2,2,4) == 12

def test_one_chip_per_gw_and_half_reset():
    used=[{'chip':'wildcard','gw':5}]
    assert chip_allowed('bench_boost',5,used)[0] is False
    assert chip_allowed('wildcard',10,used)[0] is False
    assert chip_allowed('wildcard',20,used)[0] is True

def test_free_hit_constraints():
    assert chip_allowed('free_hit',1,[])[0] is False
    used=[{'chip':'free_hit','gw':19}]
    assert chip_allowed('free_hit',20,used)[0] is False

def test_banked_ft_preserved_for_wc_and_fh():
    from src.engines.fpl_rules_2026 import CHIPS
    assert CHIPS['wildcard']['preserve_banked_ft'] is True
    assert CHIPS['free_hit']['preserve_banked_ft'] is True
