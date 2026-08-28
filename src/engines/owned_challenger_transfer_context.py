from __future__ import annotations

import json
from typing import Any

from src.utils import DATA, atomic_json, read_json

OUT = DATA / "owned_challenger_comparator.json"


def _active_planning_chip(team: dict[str, Any]) -> dict[str, Any]:
    baseline = team.get("projection_baseline") if isinstance(team.get("projection_baseline"), dict) else {}
    applied = baseline.get("override_applied") is True
    kind = str(baseline.get("override_kind") or "").upper()
    target_gw = baseline.get("override_target_gw")
    if applied and kind in {"WILDCARD", "FREE_HIT"}:
        return {
            "state": "VERIFIED_USER_PLANNING_OVERRIDE",
            "chip": kind,
            "target_gw": target_gw,
            "authority": baseline.get("effective_authority"),
            "source": baseline.get("authority_source"),
        }
    return {
        "state": "NO_VERIFIED_ACTIVE_TRANSFER_CHIP",
        "chip": None,
        "target_gw": target_gw,
        "authority": baseline.get("effective_authority"),
        "source": baseline.get("authority_source"),
    }


def _opportunity_cost(chip: dict[str, Any]) -> dict[str, Any]:
    if chip.get("chip") == "WILDCARD":
        return {
            "state": "WILDCARD_ACTIVE",
            "free_transfer_cost_applied": False,
            "hit_cost_applied": False,
            "reason": "active Wildcard makes ordinary FT/hit costs irrelevant for this comparison",
        }
    if chip.get("chip") == "FREE_HIT":
        return {
            "state": "FREE_HIT_ACTIVE",
            "free_transfer_cost_applied": False,
            "hit_cost_applied": False,
            "reason": "Free Hit is active; permanent-transfer value must not be treated as a normal transfer recommendation",
        }
    return {
        "state": "PENDING_VERIFIED_TRANSFER_STATE",
        "free_transfer_cost_applied": None,
        "hit_cost_applied": None,
        "reason": "normal FT/hit opportunity cost requires authoritative current transfer state; no cost is fabricated",
    }


def run() -> dict[str, Any]:
    payload = read_json(OUT, {})
    team = read_json(DATA / "team.json", {})
    if payload.get("contract") != "OWNED_CHALLENGER_COMPARATOR_V1":
        raise RuntimeError("comparator transfer context requires OWNED_CHALLENGER_COMPARATOR_V1")
    chip = _active_planning_chip(team)
    opportunity = _opportunity_cost(chip)
    for row in payload.get("comparisons") or []:
        row["active_chip_state"] = chip
        row["opportunity_cost"] = opportunity
        if chip.get("chip") == "FREE_HIT" and row.get("decision") in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
            row["decision"] = "REVIEW"
            row.setdefault("decision_risks", []).append("Free Hit active: permanent transfer recommendation is not directly applicable")
    comparison_by_key = {
        (int((row.get("player_out") or {}).get("element") or -1), int((row.get("player_in") or {}).get("element") or -1)): row
        for row in payload.get("comparisons") or []
    }
    refreshed_top = []
    for old in payload.get("top_comparisons") or []:
        key = (int((old.get("player_out") or {}).get("element") or -1), int((old.get("player_in") or {}).get("element") or -1))
        refreshed_top.append(comparison_by_key.get(key, old))
    payload["top_comparisons"] = refreshed_top
    payload["transfer_context"] = {
        "active_chip": chip,
        "opportunity_cost_policy": opportunity,
        "ordinary_ft_or_hit_costs_not_fabricated": True,
    }
    payload.setdefault("governance", {})["active_wildcard_does_not_apply_ft_or_hit_cost"] = True
    atomic_json(OUT, payload)
    return {
        "status": "PASS",
        "chip": chip.get("chip"),
        "opportunity_cost_state": opportunity.get("state"),
        "comparisons": len(payload.get("comparisons") or []),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
