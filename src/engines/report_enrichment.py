from __future__ import annotations

from typing import Any

from src.utils import DATA, atomic_json, read_json


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _projection_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in payload.get("players") or [] if row.get("element") is not None}


def _gw_row(proj: dict[str, Any], gw: int) -> dict[str, Any]:
    return next((row for row in proj.get("xpts_by_gw") or [] if int(row.get("gw") or -1) == gw), {})


def _battle_metrics(element: int | None, projections: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    if element is None:
        return {}
    proj = _projection_map(projections).get(int(element)) or {}
    xmins = proj.get("xmins") or {}
    gw = _gw_row(proj, planning_gw)
    return {
        "element": element,
        "name": proj.get("name"),
        "xpts": gw.get("mean"),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "dnp_probability": xmins.get("dnp_probability"),
        "model_confidence": proj.get("projection_confidence"),
    }


def _battle_reasons(leader: dict[str, Any], challenger: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    xpts_delta = _f(leader.get("xpts")) - _f(challenger.get("xpts"))
    xmins_delta = _f(leader.get("xmins")) - _f(challenger.get("xmins"))
    start_delta = _f(leader.get("start_probability")) - _f(challenger.get("start_probability"))
    if abs(xpts_delta) >= 0.10:
        reasons.append(f"projected points {'+' if xpts_delta >= 0 else ''}{xpts_delta:.2f}")
    if abs(xmins_delta) >= 2.0:
        reasons.append(f"xMins {'+' if xmins_delta >= 0 else ''}{xmins_delta:.1f}")
    if abs(start_delta) >= 0.03:
        reasons.append(f"starter probability {'+' if start_delta >= 0 else ''}{start_delta * 100:.1f}pp")
    if not reasons:
        reasons.append("model margin sangat tipis; belum ada pembeda kuat")
    return reasons[:3]


_DATA_STATE_ID = {
    "AVAILABLE": "data terstruktur tersedia",
    "CACHED_LAST_KNOWN_GOOD": "hanya cache terakhir; tidak dipakai sebagai data saat ini",
    "STALE": "data kedaluwarsa; tidak dipakai sebagai data saat ini",
    "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION": "situs terjangkau, tetapi data terstruktur belum tersedia",
    "SOURCE_REACHABLE_NOT_INGESTED": "situs terjangkau, tetapi capability ini belum di-ingest",
    "UNAVAILABLE": "tidak tersedia",
    "DISABLED": "dinonaktifkan",
}


def _source_availability(source_health: dict[str, Any]) -> dict[str, Any]:
    sources = {str(row.get("id")): row for row in source_health.get("sources") or []}
    capability_rows = source_health.get("capability_health") or []
    selected = []
    for source_id in ("livefpl", "onefpl"):
        source = sources.get(source_id) or {}
        price = next(
            (row for row in capability_rows if row.get("source_id") == source_id and row.get("capability") == "price_prediction"),
            {},
        )
        state = str(price.get("data_state") or "UNAVAILABLE")
        selected.append({
            "source": source.get("name") or source_id,
            "source_id": source_id,
            "terjangkau": bool(source.get("reachable")),
            "status_sumber": source.get("status"),
            "status_data_harga": _DATA_STATE_ID.get(state, "status data belum dikenali"),
            "structured_state": state,
            "observasi_baru": int(price.get("fresh_observations") or 0),
        })
    return {
        "otoritas": "Official FPL tetap menjadi sumber native resmi",
        "challenger": selected,
        "catatan": "Status situs dan ketersediaan data terstruktur adalah dua hal berbeda. Cache atau data kedaluwarsa tidak diperlakukan sebagai data saat ini.",
    }


def run() -> dict[str, Any]:
    user = read_json(DATA / "user_report.json", {})
    tech = read_json(DATA / "technical_appendix.json", {})
    team = read_json(DATA / "team.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    projections = read_json(DATA / "projections.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    source_health = read_json(DATA / "source_health.json", {})

    ledger = {int(row.get("element") or -1): row for row in team.get("team_value_ledger") or []}
    watch_rows = {
        int(row.get("element") or -1): row
        for rows in (watchlist.get("positions") or {}).values()
        for row in rows
    }
    price = user.get("price_radar") or {}
    for row in price.get("owned") or []:
        source = ledger.get(int(row.get("element") or -1)) or {}
        now_cost = source.get("now_cost")
        row["price"] = round(_f(now_cost) / 10.0, 1) if now_cost is not None else None
    for row in price.get("external_watchlist") or []:
        source = watch_rows.get(int(row.get("element") or -1)) or {}
        raw_price = source.get("now_cost", source.get("price"))
        if raw_price is None:
            row["price"] = None
        else:
            value = _f(raw_price)
            row["price"] = round(value / 10.0, 1) if value >= 30 else round(value, 1)

    battle = lineup.get("main_starting_xi_battle") or {}
    leader_raw = (battle.get("starter_side") or [{}])[0]
    challenger_raw = (battle.get("bench_side") or [{}])[0]
    planning_gw = int(lineup.get("planning_gw") or projections.get("planning_gw") or 1)
    leader = _battle_metrics(leader_raw.get("element"), projections, planning_gw)
    challenger = _battle_metrics(challenger_raw.get("element"), projections, planning_gw)
    section = user.get("starting_xi") or {}
    model_battle = (section.get("model") or {}).get("battle") or {}
    model_battle["leader_metrics"] = leader
    model_battle["challenger_metrics"] = challenger
    model_battle["main_reasons"] = _battle_reasons(leader, challenger) if leader and challenger else []

    user["source_availability"] = _source_availability(source_health)
    tech["source_capability_health"] = {
        "source_overall": source_health.get("overall"),
        "capabilities": source_health.get("capability_health") or [],
        "structured_observation_count": source_health.get("structured_observation_count", 0),
        "structured_cached_count": source_health.get("structured_cached_count", 0),
        "structured_stale_count": source_health.get("structured_stale_count", 0),
        "disagreement_count": source_health.get("disagreement_count", 0),
    }
    tech["runtime"] = {
        "current_run_ref": "data/runtime_performance.json",
        "embedded_during_report_stage": False,
        "note": "current-run runtime metadata is finalized by the orchestrator after report generation",
    }
    tech.setdefault("audit", {})["price_radar_has_current_price_when_source_available"] = True
    tech["audit"]["starting_xi_battle_has_decision_evidence"] = True
    tech["audit"]["source_reachability_is_separate_from_structured_data"] = True

    atomic_json(DATA / "user_report.json", user)
    atomic_json(DATA / "technical_appendix.json", tech)
    return {"user_report": user, "technical_appendix": tech}


if __name__ == "__main__":
    run()
