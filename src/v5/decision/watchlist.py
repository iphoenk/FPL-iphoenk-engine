from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_watchlist_registry.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _owned_ids(team: dict[str, Any]) -> set[int]:
    rows = team.get("team_value_ledger") or team.get("squad") or []
    return {int(row.get("element")) for row in rows if isinstance(row, dict) and row.get("element") is not None}


def _position(player: dict[str, Any]) -> str:
    raw = str(player.get("position") or "").upper()
    aliases = {"1": "GK", "2": "DEF", "3": "MID", "4": "FWD", "GKP": "GK"}
    return aliases.get(raw, raw)


def _dimension_scores(player: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, Any]]:
    xmins = player.get("xmins") if isinstance(player.get("xmins"), dict) else {}
    role = player.get("role") if isinstance(player.get("role"), dict) else {}
    current = player.get("current_season") if isinstance(player.get("current_season"), dict) else {}
    hist = player.get("historical_prior") if isinstance(player.get("historical_prior"), dict) else {}
    norm = cfg.get("normalization") or {}
    start_p = _f(xmins.get("start_probability"))
    exp_mins = _f(xmins.get("expected_minutes"))
    x5 = _f(player.get("xpts_5"))
    x15 = _f(player.get("xpts_15"))
    cost_m = max(0.1, _f(player.get("now_cost")) / 10.0)
    xg = _f(current.get("expected_goals") or current.get("xg") or hist.get("xg_per90"))
    xa = _f(current.get("expected_assists") or current.get("xa") or hist.get("xa_per90"))
    role_present = bool(role)
    hist_present = bool(hist)
    role_conf = _f(role.get("confidence") or role.get("role_confidence"), 0.0)
    if role_present and role_conf == 0.0:
        role_conf = 0.6
    set_piece_present = any(
        value is not None
        for source in (role, hist, player)
        for key in ("penalty_share", "penalty_role", "set_piece_share", "set_piece_role")
        for value in (source.get(key),)
    )
    attacking_evidence = bool(current) or hist_present
    scores: dict[str, float | None] = {
        "role": _clip(role_conf) if role_present else None,
        "xmins": _clip((start_p * 0.65) + (_clip(exp_mins / 90.0) * 0.35)) if xmins else None,
        "fixtures_3_5": _clip(x5 / _f(norm.get("xpts_5_reference"), 30.0)) if x5 > 0 else None,
        "strategic_10_15": _clip(x15 / _f(norm.get("xpts_15_reference"), 85.0)) if x15 > 0 else None,
        "underlying": _clip((xg + xa) / 1.2) if attacking_evidence else None,
        "historical_prior": _clip(_f(hist.get("minutes")) / 2500.0) if hist_present else None,
        "system_fit": _clip(max(role_conf, start_p)) if role_present or xmins else None,
        "competition": _clip(start_p) if xmins else None,
        "set_piece_penalty": 1.0 if set_piece_present else (0.35 if role_present else None),
        "price_value": _clip((x5 / cost_m) / _f(norm.get("value_reference_xpts_per_million"), 4.5)) if x5 > 0 else None,
        "squad_fit": 0.5,
    }
    evidence = {
        "start_probability": start_p,
        "expected_minutes": exp_mins,
        "xpts_5": x5,
        "xpts_15": x15,
        "now_cost": player.get("now_cost"),
        "ownership_pct": player.get("ownership_pct"),
        "projection_confidence": player.get("projection_confidence"),
        "role_available": role_present,
        "historical_prior_available": hist_present,
        "set_piece_penalty_evidence": set_piece_present,
    }
    return scores, evidence


def build_watchlist(prediction: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    weights = {str(k): _f(v) for k, v in (cfg.get("dimensions") or {}).items()}
    positions = [str(x) for x in cfg.get("positions") or ["GK", "DEF", "MID", "FWD"]]
    owned = _owned_ids(team)
    ranked: dict[str, list[dict[str, Any]]] = {p: [] for p in positions}
    rejected = 0
    for player in prediction.get("players") or []:
        if not isinstance(player, dict) or player.get("element") is None:
            continue
        element = int(player["element"])
        if element in owned and bool(cfg.get("exclude_owned", True)):
            continue
        position = _position(player)
        if position not in ranked:
            continue
        scores, evidence = _dimension_scores(player, cfg)
        available_weight = sum(weights.get(key, 0.0) for key, value in scores.items() if value is not None)
        total_weight = sum(weights.values()) or 1.0
        coverage = available_weight / total_weight
        xmins = player.get("xmins") or {}
        eligible = (
            coverage >= _f(cfg.get("minimum_dimension_coverage"), 0.78)
            and _f(xmins.get("start_probability")) >= _f(cfg.get("minimum_start_probability"), 0.55)
            and _f(xmins.get("expected_minutes")) >= _f(cfg.get("minimum_expected_minutes"), 50.0)
        )
        if not eligible:
            rejected += 1
            continue
        weighted = sum(weights.get(key, 0.0) * _f(value) for key, value in scores.items() if value is not None)
        score = weighted / max(available_weight, 1e-9)
        ranked[position].append({
            "element": element,
            "name": player.get("name"),
            "position": position,
            "team_id": player.get("team_id"),
            "price": round(_f(player.get("now_cost")) / 10.0, 1),
            "score": round(score, 4),
            "dimension_coverage": round(coverage, 4),
            "dimensions": scores,
            "evidence": evidence,
            "action": "WATCH",
        })
    limit = int(cfg.get("max_per_position") or 5)
    for position in positions:
        ranked[position] = sorted(ranked[position], key=lambda row: (-_f(row.get("score")), -_f((row.get("evidence") or {}).get("xpts_5"))))[:limit]
    ready_count = sum(len(rows) for rows in ranked.values())
    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "screening_contract": cfg.get("model_id"),
        "status": "READY" if ready_count else "INSUFFICIENT_EVIDENCE",
        "positions": ranked,
        "candidate_count": ready_count,
        "rejected_incomplete_or_low_xmins": rejected,
        "owned_excluded": len(owned),
        "governance": cfg.get("governance") or {},
    }
