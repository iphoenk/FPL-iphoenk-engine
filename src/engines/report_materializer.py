from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "report_artifact_registry.json"
BRIEF_OUT = DATA / "decision_brief.json"
DEEP_OUT = DATA / "deep_review_payload.json"
WATCH_OUT = DATA / "dss_watchlist_summary.json"
OWNED_DETAIL_OUT = DATA / "official_detail_owned.json"
WATCH_DETAIL_OUT = DATA / "official_detail_watchlist.json"
USER_OUT = DATA / "user_report.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _contract() -> dict[str, Any]:
    return load_registry().get("consumer_contract") or {}


def _owned_rows(user: dict[str, Any], team: dict[str, Any], projections: dict[str, Any]) -> list[dict[str, Any]]:
    pmap = {int(x.get("element")): x for x in projections.get("players") or [] if x.get("element") is not None}
    user_map = {int(x.get("element")): x for x in ((user.get("owned_squad") or {}).get("facts") or []) if x.get("element") is not None}
    rows: list[dict[str, Any]] = []
    ledger = team.get("team_value_ledger") or []
    for owned in ledger:
        eid = int(owned.get("element") or -1)
        source = user_map.get(eid) or {}
        proj = pmap.get(eid) or {}
        xmins = proj.get("xmins") or {}
        now_cost = owned.get("now_cost")
        price = source.get("price")
        if price is None and now_cost is not None:
            price = round(_f(now_cost) / 10.0, 1)
        rows.append({
            "element": eid,
            "name": source.get("name") or owned.get("name") or proj.get("name"),
            "position": source.get("position") or owned.get("position") or proj.get("position"),
            "price": price,
            "status": source.get("status") or owned.get("status") or proj.get("status"),
            "xmins": source.get("xmins") if source.get("xmins") is not None else xmins.get("expected_minutes"),
            "start_probability": source.get("start_probability") if source.get("start_probability") is not None else xmins.get("start_probability"),
            "model_confidence": source.get("model_confidence") or proj.get("projection_confidence"),
        })
    expected = int(_contract().get("owned_count") or 15)
    if len(rows) != expected:
        raise RuntimeError(f"report materializer owned contract failed: {len(rows)} != {expected}")
    return rows


def _watch_row(row: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    xmins = row.get("xmins") or {}
    horizons = row.get("horizons") or {}
    price_risk = row.get("price_risk") or {}
    base = {
        "element": row.get("element"),
        "rank": row.get("rank"),
        "lifecycle": row.get("lifecycle"),
        "name": row.get("name"),
        "team": row.get("team"),
        "position": row.get("position"),
        "price": row.get("price") if row.get("price") is not None else (round(_f(row.get("now_cost")) / 10.0, 1) if row.get("now_cost") is not None else None),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "xpts_5": (horizons.get("5") or {}).get("mean"),
        "confidence": row.get("projection_confidence"),
        "action": row.get("action") or "WATCH",
        "main_reason": ((row.get("reasons") or [None])[0]),
        "main_risk": ((row.get("risks") or [None])[0]),
        "price_risk": {
            "direction": price_risk.get("risk_direction"),
            "urgency": price_risk.get("urgency"),
            "progress_pct": price_risk.get("official_progress_pct"),
        },
    }
    if deep:
        base["horizons"] = {
            key: (horizons.get(key) or {}).get("mean") for key in ("3", "5", "10", "15")
        }
        base["reasons"] = list(row.get("reasons") or [])[:3]
        base["risks"] = list(row.get("risks") or [])[:3]
        replacement = row.get("direct_replacement_context") or {}
        base["direct_replacement"] = {
            "owned_name": replacement.get("owned_name"),
            "candidate_h5_delta": replacement.get("candidate_h5_delta"),
        }
        base["dss_score"] = row.get("dss_score")
        base["evidence_coverage"] = row.get("evidence_coverage")
    return base


def _watchlist_summary(watchlist: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    contract = _contract()
    positions = list(contract.get("watchlist_positions") or ["GK", "DEF", "MID", "FWD"])
    target_per = int(contract.get("watchlist_per_position") or 5)
    target_total = int(contract.get("watchlist_total") or 20)
    owned_ids = set()
    team = read_json(DATA / "team.json", {})
    for row in team.get("team_value_ledger") or []:
        if row.get("element") is not None:
            owned_ids.add(int(row["element"]))
    result: dict[str, list[dict[str, Any]]] = {}
    published: list[int] = []
    for position in positions:
        rows = list((watchlist.get("positions") or {}).get(position) or [])
        if len(rows) != target_per:
            raise RuntimeError(f"report materializer watchlist {position} contract failed: {len(rows)} != {target_per}")
        compact = [_watch_row(row, deep=deep) for row in rows]
        for row in compact:
            eid = int(row.get("element") or -1)
            if eid in owned_ids:
                raise RuntimeError(f"owned player leaked into watchlist: {eid}")
            published.append(eid)
        result[position] = compact
    if len(published) != target_total or len(set(published)) != target_total:
        raise RuntimeError(f"report materializer watchlist total contract failed: {len(published)} != {target_total}")
    return {
        "status": watchlist.get("status"),
        "screening_contract": watchlist.get("screening_contract"),
        "count": len(published),
        "per_position": target_per,
        "positions": result,
    }


def _finance(team: dict[str, Any]) -> dict[str, Any]:
    market = team.get("market_value")
    sell = team.get("sell_value")
    itb = team.get("itb")
    if market is None:
        market = sum(int(x.get("now_cost") or 0) for x in team.get("team_value_ledger") or [])
    if sell is None:
        sell = sum(int(x.get("sell_cost") or 0) for x in team.get("team_value_ledger") or [])
    if itb is None:
        itb = 0
    return {
        "squad_market_value": round(_f(market) / 10.0, 1),
        "itb": round(_f(itb) / 10.0, 1),
        "total_team_value": round((_f(market) + _f(itb)) / 10.0, 1),
        "squad_sell_value": round(_f(sell) / 10.0, 1),
        "spendable_value": round((_f(sell) + _f(itb)) / 10.0, 1),
    }


def _compact_battle(user: dict[str, Any]) -> dict[str, Any]:
    section = user.get("starting_xi") or {}
    battle = ((section.get("model") or {}).get("battle") or {})
    return {
        "formation": (section.get("facts") or {}).get("formation"),
        "decision": section.get("decision"),
        "confidence": (section.get("model") or {}).get("confidence"),
        "starter": battle.get("starter"),
        "challenger": battle.get("challenger"),
        "margin": battle.get("margin"),
        "main_reasons": battle.get("main_reasons") or [],
        "leader_metrics": battle.get("leader_metrics") or {},
        "challenger_metrics": battle.get("challenger_metrics") or {},
    }


def _captain(user: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
    section = user.get("captaincy") or {}
    model = section.get("model") or {}
    captain = model.get("captain") or {}
    vice = model.get("vice") or {}
    out = {
        "decision": section.get("decision"),
        "confidence": section.get("confidence"),
        "captain": captain.get("name") or (section.get("facts") or {}).get("model_candidate"),
        "vice": vice.get("name") or (section.get("facts") or {}).get("vice_candidate"),
        "reason": section.get("reason"),
    }
    if deep:
        out["captain_model"] = captain
        out["vice_model"] = vice
        out["checks"] = model.get("checks") or {}
        out["candidate_margin"] = model.get("candidate_margin")
    return out


def _price(user: dict[str, Any]) -> dict[str, Any]:
    section = user.get("price_radar") or {}
    keys = ("element", "name", "price", "direction", "urgency", "progress_pct", "estimated_change_time", "confidence_note", "action")
    def compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: row.get(key) for key in keys if row.get(key) is not None} for row in rows]
    return {
        "decision": section.get("decision"),
        "owned": compact(list(section.get("owned") or [])),
        "external_watchlist": compact(list(section.get("external_watchlist") or [])),
    }


def _official_partition(full: dict[str, Any], ids: set[int]) -> dict[str, Any]:
    summaries = full.get("element_summaries") or {}
    selected = {}
    for eid in sorted(ids):
        source = summaries.get(str(eid))
        if not isinstance(source, dict):
            continue
        selected[str(eid)] = {
            "fixtures": list(source.get("fixtures") or [])[:5],
            "history": list(source.get("history") or [])[-5:],
            "history_past": source.get("history_past") or [],
        }
    return {
        "generated_at": full.get("generated_at"),
        "requested_ids": sorted(ids),
        "available_count": len(selected),
        "element_summaries": selected,
        "set_piece_notes": full.get("set_piece_notes"),
        "source": "data/official_detail.json",
        "lazy_load": True,
    }


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _enforce_sizes() -> dict[str, int]:
    artifacts = load_registry().get("artifacts") or {}
    sizes = {}
    for name, spec in artifacts.items():
        raw_path = str(spec.get("path") or "")
        if not raw_path.startswith("data/"):
            continue
        path = DATA / raw_path.removeprefix("data/")
        if not path.exists():
            continue
        size = _size(path)
        sizes[name] = size
        limit = spec.get("max_bytes")
        if limit is not None and spec.get("priority") == "P0" and size > int(limit):
            raise RuntimeError(f"P0 report serving artifact too large: {name} {size}>{limit}")
    return sizes


def run() -> dict[str, Any]:
    user = read_json(USER_OUT, {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    team = read_json(DATA / "team.json", {})
    projections = read_json(DATA / "projections.json", {})
    latest = read_json(DATA / "latest.json", {})
    official = read_json(DATA / "official_detail.json", {})

    owned = _owned_rows(user, team, projections)
    watch_summary = _watchlist_summary(watchlist, deep=False)
    watch_deep = _watchlist_summary(watchlist, deep=True)

    # USER_REPORT remains decision-first but is materialized into a serving-safe form.
    user.setdefault("owned_squad", {})["count"] = len(owned)
    user["owned_squad"]["facts"] = owned
    user["owned_squad"]["compact_summary"] = None
    user["external_watchlist"] = {"status": watch_summary["status"], "decision": "WATCH", "count": watch_summary["count"], "positions": watch_summary["positions"]}
    user["serving_contract"] = {"owned": len(owned), "watchlist": watch_summary["count"], "watchlist_per_position": watch_summary["per_position"]}
    atomic_json(USER_OUT, user)

    brief = {
        "decision": user.get("decision"),
        "generated_at": _now(),
        "planning_gw": user.get("planning_gw"),
        "serving_contract": {"owned": len(owned), "watchlist": watch_summary["count"], "watchlist_per_position": watch_summary["per_position"]},
        "finance": _finance(team),
        "owned_15": owned,
        "changes_since_last_report": user.get("changes_since_last_report"),
        "main_starting_xi_battle": _compact_battle(user),
        "captaincy": _captain(user, deep=False),
        "chip": user.get("chip"),
        "price_radar": _price(user),
        "watchlist_20": watch_summary["positions"],
        "engine": user.get("engine_line"),
        "action_board": user.get("action_board") or [],
    }
    deep = {
        **brief,
        "payload_type": "DEEP_REVIEW_PAYLOAD_V1",
        "watchlist_20": watch_deep["positions"],
        "captaincy": _captain(user, deep=True),
        "starting_xi": user.get("starting_xi"),
        "horizon_policy": user.get("horizon_policy"),
        "report_mode": user.get("report_mode"),
        "technical_refs": {
            "appendix": "data/technical_appendix.json",
            "full_watchlist": "data/dss_watchlist.json",
            "official_detail_full": "data/official_detail.json",
            "official_detail_owned": "data/official_detail_owned.json",
            "official_detail_watchlist": "data/official_detail_watchlist.json",
        },
    }
    atomic_json(WATCH_OUT, watch_summary)
    atomic_json(BRIEF_OUT, brief)
    atomic_json(DEEP_OUT, deep)

    owned_ids = {int(x["element"]) for x in owned}
    watch_ids = {int(x["element"]) for rows in watch_summary["positions"].values() for x in rows}
    atomic_json(OWNED_DETAIL_OUT, _official_partition(official, owned_ids))
    atomic_json(WATCH_DETAIL_OUT, _official_partition(official, watch_ids))

    latest.setdefault("files", {}).update({
        "decision_brief": "data/decision_brief.json",
        "deep_review_payload": "data/deep_review_payload.json",
        "dss_watchlist_summary": "data/dss_watchlist_summary.json",
        "official_detail_owned": "data/official_detail_owned.json",
        "official_detail_watchlist": "data/official_detail_watchlist.json",
        "report_artifact_registry": "config/report_artifact_registry.json",
    })
    latest["report_serving"] = {
        "registry": "REPORT_ARTIFACT_REGISTRY_V1",
        "default_fast_artifact": "data/decision_brief.json",
        "default_deep_review_artifact": "data/deep_review_payload.json",
        "owned_count": len(owned),
        "watchlist_count": watch_summary["count"],
        "watchlist_per_position": watch_summary["per_position"],
        "technical_lazy_load": True,
    }
    atomic_json(DATA / "latest.json", latest)
    sizes = _enforce_sizes()
    return {"decision_brief": brief, "deep_review_payload": deep, "watchlist_summary": watch_summary, "artifact_sizes": sizes}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "owned": out["decision_brief"]["serving_contract"]["owned"],
        "watchlist": out["decision_brief"]["serving_contract"]["watchlist"],
        "artifact_sizes": out["artifact_sizes"],
    }, ensure_ascii=False))
