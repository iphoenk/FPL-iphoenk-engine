from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from src.utils import DATA, CONFIG, atomic_json, read_json

OUTFILE = DATA / "lineup_decision_v4.json"
LEGAL_FORMATIONS = [(d,m,10-d-m) for d in range(3,6) for m in range(2,6) if 1 <= 10-d-m <= 3]


def _f(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


def _fixture_row(pred: dict, idx: int = 0) -> dict:
    fx = pred.get("fixtures") or []
    return fx[idx] if idx < len(fx) and isinstance(fx[idx], dict) else {}


def _xmins_meta(fx: dict) -> dict:
    x = fx.get("xmins") or {}
    return x if isinstance(x, dict) else {}


def _player_row(pred: dict, universe_row: dict, idx: int = 0) -> dict:
    fx = _fixture_row(pred, idx)
    xm = _xmins_meta(fx)
    xpts = _f(fx.get("xpts"))
    lower = _f(fx.get("lower80"), xpts)
    upper = _f(fx.get("upper80"), xpts)
    start = _f(xm.get("start_probability"), 1.0 if _f(xm.get("expected_minutes"), 90) >= 60 else 0.5)
    bench = _f(xm.get("bench_probability"), max(0.0, 1.0-start))
    dnp = _f(xm.get("dnp_probability"), max(0.0, 1.0-start-bench))
    avail = max(0.0, min(1.0, 1.0-dnp))
    ceiling = max(xpts, upper)
    floor = min(xpts, lower)
    captain_score = xpts + 0.12*(ceiling-xpts) - 0.22*dnp - 0.08*max(0.0, 0.75-start)
    vice_score = xpts + 0.05*(ceiling-xpts) - 0.45*dnp - 0.12*max(0.0, 0.85-start)
    bench_score = xpts * (0.70 + 0.30*avail) + 0.08*start
    return {
        "element": int(pred.get("element")),
        "name": universe_row.get("name") or pred.get("name") or str(pred.get("element")),
        "position": universe_row.get("position") or pred.get("position"),
        "team": universe_row.get("team") or pred.get("team"),
        "xpts": round(xpts, 4),
        "lower80": round(lower, 4),
        "upper80": round(upper, 4),
        "start_probability": round(start, 4),
        "bench_probability": round(bench, 4),
        "dnp_probability": round(dnp, 4),
        "availability": round(avail, 4),
        "captain_score": round(captain_score, 4),
        "vice_score": round(vice_score, 4),
        "bench_score": round(bench_score, 4),
    }


def _legal_xi(rows: list[dict]) -> tuple[list[dict], str, float]:
    by = {p: [r for r in rows if r["position"] == p] for p in ("GK","DEF","MID","FWD")}
    if not all(by[p] for p in by):
        raise RuntimeError("locked squad missing position group")
    gk = max(by["GK"], key=lambda r:(r["xpts"],r["start_probability"],-r["dnp_probability"]))
    best = None
    for d,m,f in LEGAL_FORMATIONS:
        if len(by["DEF"])<d or len(by["MID"])<m or len(by["FWD"])<f: continue
        chosen = [gk]
        chosen += sorted(by["DEF"], key=lambda r:(r["xpts"],r["start_probability"]), reverse=True)[:d]
        chosen += sorted(by["MID"], key=lambda r:(r["xpts"],r["start_probability"]), reverse=True)[:m]
        chosen += sorted(by["FWD"], key=lambda r:(r["xpts"],r["start_probability"]), reverse=True)[:f]
        score = sum(r["xpts"] for r in chosen)
        risk = sum(r["dnp_probability"] for r in chosen)
        key = (score - 0.08*risk, score, -risk)
        if best is None or key > best[0]: best = (key, chosen, f"{d}-{m}-{f}", score)
    if best is None: raise RuntimeError("no legal XI")
    return best[1], best[2], best[3]


def _bench(rows: list[dict], xi_ids: set[int]) -> tuple[dict,list[dict]]:
    bench = [r for r in rows if r["element"] not in xi_ids]
    gks = [r for r in bench if r["position"] == "GK"]
    outfield = [r for r in bench if r["position"] != "GK"]
    if len(gks) != 1 or len(outfield) != 3: raise RuntimeError("bench structure invalid")
    outfield.sort(key=lambda r:(r["bench_score"],r["xpts"],r["start_probability"]), reverse=True)
    return gks[0], outfield


def optimize_lineup(predictions: dict, universe: dict, locked: dict, gw_index: int = 0) -> dict:
    pmap = {int(p.get("element")): p for p in predictions.get("players", []) if p.get("element") is not None}
    umap = {int(p.get("element")): p for p in universe.get("players", []) if p.get("element") is not None}
    locked_ids = [int(p["element"]) for p in locked.get("players", [])]
    if len(locked_ids) != 15: raise RuntimeError("locked squad must contain 15 players")
    missing = [e for e in locked_ids if e not in pmap or e not in umap]
    if missing: raise RuntimeError(f"locked players missing prediction/universe data: {missing}")
    rows = [_player_row(pmap[e], umap[e], gw_index) for e in locked_ids]
    xi, formation, xi_xpts = _legal_xi(rows)
    xi_ids = {r["element"] for r in xi}
    bench_gk, bench_out = _bench(rows, xi_ids)
    captain_pool = [r for r in xi if r["position"] != "GK"] or xi
    captain = max(captain_pool, key=lambda r:(r["captain_score"],r["xpts"],r["upper80"]))
    vice_pool = [r for r in xi if r["element"] != captain["element"]]
    vice = max(vice_pool, key=lambda r:(r["vice_score"],r["xpts"],r["start_probability"]))
    chip = "WILDCARD" if bool(locked.get("wildcard_active")) else "NONE"
    return {
        "schema_version": 450,
        "engine": "v4.5-lineup-bench-captain",
        "gw_offset": gw_index+1,
        "formation": formation,
        "xi_xpts": round(xi_xpts,2),
        "starting_xi": sorted(xi, key=lambda r:(0 if r["position"]=="GK" else 1 if r["position"]=="DEF" else 2 if r["position"]=="MID" else 3,-r["xpts"])),
        "captain": captain,
        "vice_captain": vice,
        "bench": {"gk": bench_gk, "order": [{"slot":i+1, **r} for i,r in enumerate(bench_out)]},
        "chip_context": {"active_chip": chip, "other_chip_recommendation": "NONE" if chip=="WILDCARD" else "UNASSESSED", "single_chip_rule_respected": True},
        "guardrails": {"legal_formation": True, "one_gk_in_xi": True, "captain_in_xi": True, "vice_in_xi": True, "bench_has_one_gk_three_outfield": True, "captain_risk_adjusted": True},
    }


def run():
    out = optimize_lineup(read_json(DATA/"predictions_v4.json",{}), read_json(DATA/"universe.json",{}), read_json(CONFIG/"locked_squad.json",{}))
    atomic_json(OUTFILE,out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out

if __name__ == "__main__": run()
