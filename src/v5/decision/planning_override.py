from __future__ import annotations

from collections import Counter
from typing import Any

from src.v5.config_cache import load_json_config

OVERRIDE_CONFIG = "config/manual_lineup_override.json"
SQUAD_REGISTRY = "config/v5_squad_registry.json"


def _rows(lineup: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for key in ("starters", "bench"):
        for row in lineup.get(key) or []:
            if isinstance(row, dict) and row.get("element") is not None:
                out[int(row["element"])] = dict(row)
    return out


def _active_for_gw(override: dict[str, Any], planning_gw: int, phase: str) -> bool:
    status = str(override.get("status") or "INACTIVE").upper()
    if status in {"", "INACTIVE", "DISABLED", "NONE"}:
        return False
    if phase != "PRE_DEADLINE":
        return False
    if override.get("gw") is None:
        raise RuntimeError("V5 decision FAIL CLOSED: active manual lineup override requires gw")
    return int(override["gw"]) == int(planning_gw)


def _formation(starters: list[dict[str, Any]], rules: dict[str, Any]) -> str:
    counts = Counter(str(row.get("position")) for row in starters)
    if counts.get("GK", 0) != 1:
        raise RuntimeError("V5 decision FAIL CLOSED: user XI must contain exactly one GK")
    formation = f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"
    legal = {str(value) for value in ((rules.get("lineup") or {}).get("legal_formations") or [])}
    if formation not in legal:
        raise RuntimeError(f"V5 decision FAIL CLOSED: illegal user formation {formation}")
    return formation


def apply_user_lineup_override(
    engine_lineup: dict[str, Any],
    *,
    truth: dict[str, Any],
    rules: dict[str, Any],
    planning_gw: int,
    override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if engine_lineup.get("status") != "READY":
        return engine_lineup, {
            "active": False,
            "reason": "ENGINE_LINEUP_NOT_READY",
            "engine_recommendation_preserved": True,
        }

    engine = {
        **engine_lineup,
        "chip_context": dict(truth.get("chip_state") or {}),
    }
    cfg = load_json_config(OVERRIDE_CONFIG) if override is None else dict(override)
    phase = str(((truth.get("context") or {}).get("phase") or ""))
    policy = (load_json_config(SQUAD_REGISTRY).get("planning_override") or {})
    active = _active_for_gw(cfg, planning_gw, phase)
    if not active:
        stale = str(cfg.get("status") or "INACTIVE").upper() not in {"", "INACTIVE", "DISABLED", "NONE"} and cfg.get("gw") is not None and int(cfg.get("gw")) != int(planning_gw)
        return engine, {
            "active": False,
            "reason": "STALE_TARGET_GW" if stale else "NO_EXPLICIT_USER_OVERRIDE",
            "target_gw": cfg.get("gw"),
            "planning_gw": int(planning_gw),
            "engine_recommendation_preserved": True,
            "post_deadline_official_submission_reclaims_authority": phase != "PRE_DEADLINE",
        }

    pmap = _rows(engine)
    if len(pmap) != 15:
        raise RuntimeError(f"V5 decision FAIL CLOSED: expected 15 owned lineup rows, got {len(pmap)}")
    xi_ids = [int(value) for value in (cfg.get("starting_xi") or [])]
    if len(xi_ids) != 11 or len(set(xi_ids)) != 11:
        raise RuntimeError("V5 decision FAIL CLOSED: user starting_xi must contain 11 unique elements")
    if any(element not in pmap for element in xi_ids):
        raise RuntimeError("V5 decision FAIL CLOSED: user XI contains player outside authoritative squad")

    captain = int(cfg.get("captain") or 0)
    vice = int(cfg.get("vice_captain") or 0)
    if captain == vice or captain not in xi_ids or vice not in xi_ids:
        raise RuntimeError("V5 decision FAIL CLOSED: captain and vice must be distinct XI members")

    remaining = set(pmap) - set(xi_ids)
    bench_gk = int(cfg.get("bench_gk") or 0)
    bench_order = [int(value) for value in (cfg.get("bench_order") or [])]
    if bench_gk not in remaining or str(pmap[bench_gk].get("position")) != "GK":
        raise RuntimeError("V5 decision FAIL CLOSED: invalid user bench_gk")
    if len(bench_order) != 3 or set(bench_order) != remaining - {bench_gk}:
        raise RuntimeError("V5 decision FAIL CLOSED: bench_order must contain all three remaining outfield players")

    starters = [pmap[element] for element in xi_ids]
    formation = _formation(starters, rules)
    bench = [pmap[element] for element in bench_order] + [pmap[bench_gk]]
    chip_context = dict(engine.get("chip_context") or {})
    if cfg.get("active_chip") is not None:
        chip_context["active_chip"] = str(cfg.get("active_chip") or "").lower() or None
        chip_context["source"] = cfg.get("source") or "USER_MANUAL_DECISION"

    effective = {
        **engine,
        "formation": formation,
        "starters": starters,
        "bench": bench,
        "captain": pmap[captain],
        "vice_captain": pmap[vice],
        "chip_context": chip_context,
        "authority": "user_manual_decision",
        "user_override": {
            "active": True,
            "target_gw": int(planning_gw),
            "source": cfg.get("source") or "USER_MANUAL_DECISION",
            "note": cfg.get("note"),
        },
    }
    return effective, {
        "active": True,
        "target_gw": int(planning_gw),
        "source": cfg.get("source") or "USER_MANUAL_DECISION",
        "engine_recommendation_preserved": bool(policy.get("engine_recommendation_preserved_for_comparison", True)),
        "lineup_legality_fail_closed": bool(policy.get("lineup_legality_fail_closed", True)),
        "captain_and_vice_must_be_distinct_xi_members": bool(
            policy.get("captain_and_vice_must_be_distinct_xi_members", True)
        ),
        "engine_can_warn_but_not_overwrite_user": True,
    }
