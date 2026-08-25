from src.engines.v4_wc_package_audit import _package_class, _fast_metrics
from src.engines.v4_wc_optimizer import Candidate, squad_metrics


def test_package_class_tightens_with_more_changes():
    # Arguments are delta_best_xi_xpts_5 and delta_bench_adjusted_utility_5.
    assert _package_class(2.2, 2.0, 1) == "MATERIAL_UPGRADE"
    assert _package_class(2.2, 2.0, 2) != "MATERIAL_UPGRADE"


def test_package_class_keep_small_signal():
    assert _package_class(0.4, 0.05, 1) == "KEEP_BASELINE"


def test_single_pass_metrics_match_reference():
    players=[]; e=1
    spec=[("GK",2),("DEF",5),("MID",5),("FWD",3)]
    for pos,n in spec:
        for j in range(n):
            base=2.0 + (e % 5) * .35
            gw=tuple(base + i*.07 for i in range(5))
            players.append(Candidate(e,f"P{e}",pos,(e%8)+1,f"T{(e%8)+1}",45,9+e*.01,15+e*.01,30+e*.02,45+e*.03,.15,3+e*.01,gw))
            e+=1
    ref=squad_metrics(players)
    fast=_fast_metrics(players,include_detail=True)
    for key in ("cost","objective","squad_xpts_3","squad_xpts_5","squad_xpts_10","squad_xpts_15","best_xi_xpts_5","bench_adjusted_utility_5"):
        assert fast[key] == ref[key]
    assert fast["best_xi_by_gw"] == ref["best_xi_by_gw"]
