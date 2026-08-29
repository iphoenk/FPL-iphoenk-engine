from src.v5.decision.tactical_consumption import apply_lineup_overlay, close_group_sort, tactical_key
from src.v5.services.watchlist import _tactical_overlay


def _tm(good=False):
    return {"status":"READY","player_return_routes":["box_pressure"] if good else [],"opponent_vulnerabilities":["box_pressure"] if good else [],"highlights":["material"] if good else [],"evidence_confidence":"HIGH" if good else "LOW"}


def test_close_group_tactical_can_break_close_call_but_not_large_gap():
    rows=[{"score":5.0,"player":{"tactical_matchup":_tm(False)}},{"score":4.8,"player":{"tactical_matchup":_tm(True)}}]
    close=close_group_sort(rows,score=lambda r:r["score"],player=lambda r:r["player"],gap=.35)
    assert close[0]["score"]==4.8
    far=close_group_sort(rows,score=lambda r:r["score"],player=lambda r:r["player"],gap=.10)
    assert far[0]["score"]==5.0


def test_missing_or_nonmaterial_tactical_is_neutral():
    assert tactical_key({})==(0,0,0)
    assert tactical_key({"tactical_matchup":{"status":"PARTIAL","highlights":["x"]}})==(0,0,0)


def test_watchlist_tactical_rerank_preserves_membership_set():
    prediction={"players":[
        {"element":101,"tactical_matchup":_tm(False)},
        {"element":102,"tactical_matchup":_tm(True)},
        {"element":103,"tactical_matchup":_tm(False)},
    ]}
    payload={"positions":{"MID":[{"element":101,"score":.80},{"element":102,"score":.78},{"element":103,"score":.50}]},"governance":{}}
    out=_tactical_overlay(payload,prediction)
    assert {r["element"] for r in out["positions"]["MID"]}=={101,102,103}
    assert out["positions"]["MID"][0]["element"]==102
    assert out["positions"]["MID"][-1]["element"]==103
    assert out["governance"]["tactical_membership_promotion_forbidden"] is True


def test_lineup_overlay_can_select_only_published_close_alternative(monkeypatch):
    import src.v5.decision.lineup_optimizer as lineup_optimizer
    monkeypatch.setattr(lineup_optimizer,"player_score",lambda player,gw,profile: float((player.get("scores") or {}).get(profile,5.0)))
    players=[]
    for eid in range(1,16):
        players.append({"element":eid,"name":f"P{eid}","position":"GK" if eid in {1,15} else ("DEF" if eid<7 else "MID" if eid<12 else "FWD"),"team_id":eid,"xmins":{"start_probability":.95,"dnp_probability":.02},"scores":{"player_score":5.0,"bench_score":5.0,"captain_score":6.0-(eid/100),"vice_score":5.5-(eid/100)},"tactical_matchup":_tm(eid==12)})
    prediction={"planning_gw":2,"players":players}
    base_ids=list(range(1,12)); alt_ids=list(range(1,11))+[12]
    lineup={"status":"READY","planning_gw":2,"formation":"4-4-2","starters":[{"element":eid} for eid in base_ids],"bench":[{"element":eid} for eid in range(12,16)],"captain":{"element":2},"vice_captain":{"element":3},"captain_safe_pool":[{"element":2},{"element":3}],"selection_score":55.0,"expected_starting_xi_mean":55.0,"main_starting_xi_battle":{"status":"CLOSE","margin":.2},"alternatives":[{"rank":1,"formation":"4-4-2","selection_score":55.0,"mean":55.0,"element_ids":base_ids},{"rank":2,"formation":"4-4-2","selection_score":54.8,"mean":54.8,"element_ids":alt_ids}]}
    out=apply_lineup_overlay(lineup,prediction)
    ids={row["element"] for row in out["starters"]}
    assert 12 in ids and 11 not in ids
    assert len(ids)==11 and len(out["bench"])==4
    assert out["governance"]["tactical_xi_tiebreak_applied"] is True
    assert out["main_starting_xi_battle"]["tactical_tiebreak"]["policy"].startswith("close-call")


def test_lineup_overlay_never_reaches_unpublished_external_candidate(monkeypatch):
    import src.v5.decision.lineup_optimizer as lineup_optimizer
    monkeypatch.setattr(lineup_optimizer,"player_score",lambda player,gw,profile:5.0)
    players=[{"element":eid,"name":f"P{eid}","position":"GK" if eid in {1,15} else "MID","team_id":eid,"xmins":{"start_probability":.9,"dnp_probability":.05},"tactical_matchup":_tm(eid==99)} for eid in list(range(1,16))+[99]]
    base_ids=list(range(1,12))
    lineup={"status":"READY","planning_gw":2,"formation":"3-5-2","starters":[{"element":eid} for eid in base_ids],"bench":[{"element":eid} for eid in range(12,16)],"captain":{"element":2},"vice_captain":{"element":3},"selection_score":55.0,"main_starting_xi_battle":{"status":"CLEAR","margin":1.0},"alternatives":[{"rank":1,"formation":"3-5-2","selection_score":55.0,"mean":55.0,"element_ids":base_ids}]}
    out=apply_lineup_overlay(lineup,{"planning_gw":2,"players":players[:15]})
    assert 99 not in {row["element"] for row in out["starters"]}
