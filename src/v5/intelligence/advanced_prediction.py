from __future__ import annotations
import math
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.intelligence.feature_bundle import FeatureBundle
from src.v5.intelligence.score_distribution import player_return_probabilities

CONFIG = "config/intelligence/advanced_prediction.json"

def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def _xmins_distribution(xmins: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(xmins, dict) or xmins.get("start_probability") is None:
        return None
    p_start = _clamp(_f(xmins.get("start_probability")), 0.0, 1.0)
    p_bench = _clamp(_f(xmins.get("bench_probability")), 0.0, 1.0)
    p_dnp = _clamp(_f(xmins.get("dnp_probability"), max(0.0, 1.0 - p_start - p_bench)), 0.0, 1.0)
    total = p_start + p_bench + p_dnp
    if total <= 0:
        return None
    p_start, p_bench, p_dnp = p_start / total, p_bench / total, p_dnp / total
    c = cfg.get("xmins_distribution") or {}
    starter = _clamp(_f(xmins.get("starter_minutes_if_start"), 72.0), _f(c.get("starter_minutes_floor"),45), _f(c.get("starter_minutes_ceiling"),90))
    bench = _clamp(_f(xmins.get("bench_minutes_if_used"), 18.0), _f(c.get("bench_minutes_floor"),1), _f(c.get("bench_minutes_ceiling"),35))
    expected = p_start * starter + p_bench * bench
    return {"start_probability":round(p_start,6),"bench_probability":round(p_bench,6),"dnp_probability":round(p_dnp,6),"starter_minutes_if_start":round(starter,2),"bench_minutes_if_used":round(bench,2),"expected_minutes":round(expected,2)}

def _uncertainty_split(std: float, cfg: dict[str, Any]) -> dict[str, float]:
    std=max(0.0,float(std)); u=cfg.get("uncertainty") or {}; model_share=_clamp(_f(u.get("model_share_of_variance"),0.40),0.0,1.0); model_std=std*math.sqrt(model_share); aleatoric_std=max(_f(u.get("minimum_aleatoric_std"),0.35),math.sqrt(max(0.0,std*std-model_std*model_std))); return {"total_std":round(std,4),"model_std":round(model_std,4),"aleatoric_std":round(aleatoric_std,4)}

def _sustainability(player: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    rates=player.get("rates") if isinstance(player.get("rates"),dict) else {}
    if rates.get("xg90") is None or rates.get("xa90") is None:return None
    minutes=max(0.0,_f((player.get("current_season") or {}).get("minutes"))); c=cfg.get("sustainability") or {}; sample=max(1.0,_f(c.get("small_sample_minutes"),450.0)); evidence=_clamp(minutes/sample,0.0,1.0); raw=0.88+0.12*evidence; factor=_clamp(raw,_f(c.get("shrinkage_floor"),0.78),_f(c.get("shrinkage_ceiling"),1.08)); return {"factor":round(factor,4),"evidence_minutes":round(minutes,1),"shadow_only":True}

def enrich_prediction(prediction: dict[str, Any], full_enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg=load_json_config(CONFIG); players_out=[]; aggregate=FeatureBundle(); aggregate.declare("xmins_distribution",{"contract":"xmins_distribution_v1"}); aggregate.declare("uncertainty_decomposition",{"contract":"model+aleatoric_v1"}); full_enrichment=full_enrichment if isinstance(full_enrichment,dict) else {}; schedule=full_enrichment.get("schedule") if isinstance(full_enrichment.get("schedule"),dict) else {}
    aggregate.declare("rest_congestion",{"schedule_status":schedule.get("status")},reason=None) if schedule and schedule.get("status") not in {None,"UNAVAILABLE"} else aggregate.declare("rest_congestion",reason="schedule enrichment unavailable")
    for player in prediction.get("players") or []:
        if not isinstance(player,dict):continue
        row=dict(player); bundle=FeatureBundle(); xdist=_xmins_distribution(row.get("xmins") or {},cfg); bundle.declare("xmins_distribution",xdist,reason=None if xdist else "xmins evidence incomplete")
        if xdist:bundle.consume("xmins_distribution","advanced_prediction"); aggregate.consume("xmins_distribution","advanced_prediction")
        sustainability=_sustainability(row,cfg); bundle.declare("sustainability",sustainability,reason=None if sustainability else "attacking rates unavailable")
        if sustainability:bundle.consume("sustainability","advanced_prediction")
        rates=row.get("rates") if isinstance(row.get("rates"),dict) else {}; ret=player_return_probabilities(rates.get("xg90"),rates.get("xa90"),(xdist or {}).get("expected_minutes")); bundle.declare("score_distribution",ret if ret.get("status")=="ACTIVE" else None,reason=ret.get("reason"))
        if ret.get("status")=="ACTIVE":bundle.consume("score_distribution","advanced_prediction")
        dc=rates.get("dc90"); rate_sources=rates.get("sources") if isinstance(rates.get("sources"),dict) else {}; dc_source=str(rate_sources.get("dc90") or ""); empirical_dc=dc is not None and dc_source not in {"","position_prior"}; dc_ev={"dc90":_f(dc),"probability_proxy":round(1.0-math.exp(-max(0.0,_f(dc))),6),"source":dc_source} if empirical_dc else None; bundle.declare("defcon_probability",dc_ev,reason=None if dc_ev else ("empirical defcon evidence unavailable" if dc is not None else "dc rate unavailable"))
        if dc_ev:bundle.consume("defcon_probability","advanced_prediction")
        uncertainty=_uncertainty_split(_f(row.get("uncertainty")),cfg); bundle.declare("uncertainty_decomposition",uncertainty); bundle.consume("uncertainty_decomposition","advanced_prediction"); aggregate.consume("uncertainty_decomposition","advanced_prediction")
        row["advanced"]={"xmins_distribution":xdist,"sustainability":sustainability,"return_probabilities":ret,"defcon_probability":dc_ev,"uncertainty":uncertainty,"feature_bundle":bundle.snapshot(),"authoritative_xpts_replaced":False}; players_out.append(row)
    return {**prediction,"players":players_out,"advanced_prediction":{"model":cfg.get("model_id"),"feature_bundle":aggregate.snapshot(),"authoritative_xpts_replaced":False,"promotion_requires_settled_temporal_backtest":True}}
