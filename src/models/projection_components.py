from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from src.rules import ASSIST_POINTS, CLEAN_SHEET_POINTS, DC_RULES, ELEMENT_TYPE_TO_POSITION, GOAL_POINTS
from src.utils import DATA, ROOT, read_json

CONFIG_DIR = ROOT / "config" / "intelligence"
PROJECTION_CONFIG = CONFIG_DIR / "projection.json"
TEAM_STRENGTH_OUT = DATA / "team_strength.json"


def _f(value: Any, default: float = 0.0) -> float:
    try: return float(default if value is None else value)
    except (TypeError, ValueError): return float(default)


def clamp(value: float, low: float, high: float) -> float: return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_projection_config() -> dict[str, Any]: return json.loads(PROJECTION_CONFIG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _team_strength_baseline() -> dict[str, Any]:
    return (read_json(TEAM_STRENGTH_OUT,{}) or {}).get("baseline") or {}


def _blended_rate(player: dict[str, Any], cumulative_field: str, prior: float, shrink_minutes: float) -> tuple[float, str]:
    minutes=max(0.0,_f(player.get("minutes"))); cumulative=max(0.0,_f(player.get(cumulative_field))); observed=cumulative*90.0/minutes if minutes>0 else prior
    blended=(observed*minutes+prior*shrink_minutes)/max(1e-6,minutes+shrink_minutes)
    return max(0.0,blended), "observed_shrunk_to_position_prior" if minutes>0 else "position_prior"


def robust_attack_rate(player: dict[str, Any], cumulative_field: str, prior: float, config: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    minutes=max(0.0,_f(player.get("minutes"))); cumulative=max(0.0,_f(player.get(cumulative_field)))
    if minutes<=0: return max(0.0,prior),"position_or_historical_prior",{"minutes":0.0,"raw_observed90":None,"bounded_observed90":None,"cap_multiplier":None,"shrink_minutes":None,"winsorized":False}
    tiers=list(config.get("tiers") or [])
    if not tiers: raise RuntimeError("REC-02 robust rate tiers missing")
    selected=next((tier for tier in tiers if tier.get("max_minutes") is None or minutes<=float(tier.get("max_minutes"))),tiers[-1])
    cap_multiplier=max(1.0,_f(selected.get("upper_prior_multiplier"),6.0)); shrink_minutes=max(0.0,_f(selected.get("shrink_minutes"),450.0)); raw_observed=cumulative*90.0/minutes
    upper=max(prior*cap_multiplier,_f(config.get("absolute_upper_rate90"),1.5)); bounded=clamp(raw_observed,0.0,upper); blended=(bounded*minutes+prior*shrink_minutes)/max(1e-6,minutes+shrink_minutes); winsorized=abs(bounded-raw_observed)>1e-12
    return max(0.0,blended),"robust_observed_shrunk_to_prior"+("_winsorized" if winsorized else ""),{"minutes":round(minutes,1),"raw_observed90":round(raw_observed,4),"bounded_observed90":round(bounded,4),"cap_multiplier":cap_multiplier,"shrink_minutes":shrink_minutes,"winsorized":winsorized}


def _poisson_tail_at_least(threshold: int, expected_count: float) -> float:
    if threshold<=0: return 1.0
    lam=max(0.0,float(expected_count))
    if lam<=0.0: return 0.0
    term=math.exp(-lam); cumulative=term
    for k in range(1,threshold): term*=lam/k; cumulative+=term
    return clamp(1.0-cumulative,0.0,1.0)


@lru_cache(maxsize=32)
def _poisson_rate_for_tail(threshold: int, target_probability: float) -> float:
    target=clamp(target_probability,0.0,0.999999)
    if target<=0.0: return 0.0
    low,high=0.0,max(1.0,float(threshold))
    while _poisson_tail_at_least(threshold,high)<target and high<256.0: high*=2.0
    for _ in range(64):
        mid=(low+high)/2.0
        if _poisson_tail_at_least(threshold,mid)<target: low=mid
        else: high=mid
    return (low+high)/2.0


def defensive_contribution_rate_bundle(player: dict[str, Any], feature: dict[str, Any] | None, prior_expected_points90: float, shrink_minutes: float) -> dict[str, Any]:
    element_type=int(player.get("element_type") or 4); rule=DC_RULES.get(element_type) or {}
    if not bool(rule.get("eligible")): return {"dc90":0.0,"dc_count90":0.0,"dc_threshold":None,"dc_points":0.0,"dc_source":"ineligible_position","dc_evidence_minutes":0.0,"dc_sample_quality":"INELIGIBLE"}
    threshold=int(rule.get("threshold") or 0); points=float(rule.get("points") or 0.0); prior_probability=clamp(prior_expected_points90/max(points,1e-6),0.0,0.999999); prior_count90=_poisson_rate_for_tail(threshold,prior_probability)
    advanced=(feature or {}).get("advanced_current") or {}; evidence_minutes=max(0.0,_f(advanced.get("minutes"))); observed_raw=advanced.get("dc_reconstructed_per90"); has_observed=evidence_minutes>0 and observed_raw is not None; observed=max(0.0,_f(observed_raw,prior_count90))
    if has_observed: count90=(observed*evidence_minutes+prior_count90*shrink_minutes)/max(1e-6,evidence_minutes+shrink_minutes); source="player_cbit_cbirt_shrunk_to_position_prior"
    else: count90=prior_count90; source="position_prior_probability_calibrated"
    return {"dc90":max(0.0,points*_poisson_tail_at_least(threshold,count90)),"dc_count90":max(0.0,count90),"dc_threshold":threshold,"dc_points":points,"dc_source":source,"dc_evidence_minutes":evidence_minutes,"dc_sample_quality":advanced.get("sample_quality") or "NO_ADVANCED_EVIDENCE"}


def _p60(xmins: dict[str, Any], cfg: dict[str, Any]) -> float:
    trans=cfg.get("appearance_60_probability_transition") or {}; low=_f(trans.get("start_minutes_low"),55.0); high=max(low+1.0,_f(trans.get("start_minutes_high"),70.0)); starter_minutes=_f(xmins.get("starter_minutes_if_start"),72.0)
    return clamp(_f(xmins.get("start_probability"))*clamp((starter_minutes-low)/(high-low),0.0,1.0),0.0,1.0)


def _project_fixture(player: dict[str, Any], xmins: dict[str, Any], matchup: dict[str, Any], home: bool, rate_bundle: dict[str, Any], small_sample: bool) -> dict[str, Any]:
    cfg=load_projection_config(); element_type=int(player.get("element_type") or 4); position=str(player.get("position") or ELEMENT_TYPE_TO_POSITION.get(element_type) or "FWD"); expected_minutes=max(0.0,_f(xmins.get("expected_minutes"))); share=clamp(expected_minutes/90.0,0.0,1.0); p_start=clamp(_f(xmins.get("start_probability")),0.0,1.0); p_bench=clamp(_f(xmins.get("bench_probability")),0.0,1.0-p_start); p_appearance=clamp(p_start+p_bench,0.0,1.0); p60=_p60(xmins,cfg)
    baseline=_team_strength_baseline(); team_xg=_f(matchup.get("home_expected_goals") if home else matchup.get("away_expected_goals"),1.3); league_base=_f(baseline.get("home_goals" if home else "away_goals"),1.3); attack_multiplier=clamp(team_xg/max(0.2,league_base),_f(cfg.get("attack_multiplier_min"),0.55),_f(cfg.get("attack_multiplier_max"),1.75)); cs_prob=clamp(_f(matchup.get("home_clean_sheet_probability") if home else matchup.get("away_clean_sheet_probability")),0.0,1.0)
    appearance=p_start+p_bench+p60; attack=(_f(rate_bundle.get("xg90"))*GOAL_POINTS.get(element_type,4)+_f(rate_bundle.get("xa90"))*ASSIST_POINTS)*share*attack_multiplier; clean_sheet=CLEAN_SHEET_POINTS.get(element_type,0)*cs_prob*p60; saves=(_f(rate_bundle.get("saves90"))/3.0)*share if position=="GK" else 0.0
    threshold=rate_bundle.get("dc_threshold"); count90=rate_bundle.get("dc_count90"); points=_f(rate_bundle.get("dc_points"))
    if position!="GK" and threshold is not None and count90 is not None and p_appearance>0: conditional_minutes=min(90.0,expected_minutes/max(p_appearance,1e-6)); dc=p_appearance*points*_poisson_tail_at_least(int(threshold),_f(count90)*conditional_minutes/90.0)
    else: dc=0.0
    bonus=_f(rate_bundle.get("bonus90"))*share; mean=max(0.0,appearance+attack+clean_sheet+saves+dc+bonus); unc=cfg.get("uncertainty") or {}; std=max(_f(unc.get("minimum_points_std"),1.15),mean*_f(unc.get("coefficient_of_variation"),0.42)+_f(xmins.get("minutes_std"))*_f(unc.get("xmins_std_points_multiplier"),0.035)+(_f(unc.get("small_sample_extra_std"),0.45) if small_sample else 0.0))
    return {"event":matchup.get("event"),"kickoff_time":matchup.get("kickoff_time"),"opponent":matchup.get("team_a") if home else matchup.get("team_h"),"home":home,"team_expected_goals":round(team_xg,4),"clean_sheet_probability":round(cs_prob,4),"mean":round(mean,3),"std":round(std,3),"components":{"appearance":round(appearance,3),"attack":round(attack,3),"clean_sheet":round(clean_sheet,3),"saves":round(saves,3),"defensive_contribution":round(dc,3),"bonus":round(bonus,3)}}