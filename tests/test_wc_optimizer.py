from src.engines.v4_wc_optimizer import Candidate, validate_squad, best_xi, classify_gain, squad_utility, squad_utility_fast, _club_add, _club_count


def c(e,pos,team,cost=50,x=3.0):
    return Candidate(e,str(e),pos,team,str(team),cost,x*3,x*5,x*10,x*15,0.2,x,(x,)*15)


def legal_squad():
    out=[]; eid=1
    for pos,n in {"GK":2,"DEF":5,"MID":5,"FWD":3}.items():
        for i in range(n):
            out.append(c(eid,pos,(eid%8)+1,50,3+i*.1)); eid+=1
    return out


def test_validate_legal_squad():
    ok,reason=validate_squad(legal_squad(),1000)
    assert ok and reason=="ok"


def test_club_limit_rejected():
    ps=legal_squad()
    ps[0]=c(ps[0].element,"GK",1); ps[1]=c(ps[1].element,"GK",1); ps[2]=c(ps[2].element,"DEF",1); ps[3]=c(ps[3].element,"DEF",1)
    ok,reason=validate_squad(ps,1000)
    assert not ok and reason=="club_limit"


def test_packed_club_signature_exact_counts():
    sig=0
    for _ in range(3): sig=_club_add(sig,7)
    for _ in range(2): sig=_club_add(sig,1)
    assert _club_count(sig,7)==3
    assert _club_count(sig,1)==2
    assert _club_count(sig,2)==0


def test_best_xi_is_legal_343_or_better():
    ps=legal_squad()
    score,ids=best_xi(ps,0)
    assert score>0 and len(ids)==11
    chosen=[p for p in ps if p.element in ids]
    counts={pos:sum(p.position==pos for p in chosen) for pos in ["GK","DEF","MID","FWD"]}
    assert counts["GK"]==1
    assert counts["DEF"]>=3 and counts["MID"]>=2 and counts["FWD"]>=1


def test_fast_utility_is_numerically_equivalent():
    ps=legal_squad()
    assert abs(squad_utility(ps,5)-squad_utility_fast(ps,5)) < 1e-9


def test_gain_classification_requires_material_margin():
    assert classify_gain(.5,.5)=="KEEP_15"
    assert classify_gain(2.1,1.6)=="OPTIONAL_IMPROVEMENT"
    assert classify_gain(5.0,4.2)=="MATERIAL_UPGRADE"
