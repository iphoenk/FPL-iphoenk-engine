from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "owned_challenger_comparator.json"
OUT = DATA / "challenger_discovery.json"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _horizon(proj: dict[str, Any], horizon: int) -> float:
    if proj.get("horizons"):
        return _f(((proj.get("horizons") or {}).get(str(horizon)) or {}).get("mean"))
    return round(sum(_f(row.get("mean")) for row in list(proj.get("xpts_by_gw") or [])[:horizon]), 3)


def _official_map(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("id")): row
        for row in ((snapshot.get("bootstrap") or {}).get("elements") or [])
        if _i(row.get("id")) > 0
    }


def _fixture_context(snapshot: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for row in snapshot.get("fixtures") or []:
        event = row.get("event")
        if event is None:
            continue
        for team_key, opp_key, home in (("team_h", "team_a", True), ("team_a", "team_h", False)):
            team_id = _i(row.get(team_key))
            if team_id <= 0:
                continue
            out.setdefault(team_id, []).append({
                "event": event,
                "opponent_team_id": _i(row.get(opp_key)),
                "home": home,
                "kickoff_time": row.get("kickoff_time"),
                "started": bool(row.get("started")),
                "finished": bool(row.get("finished")),
            })
    for rows in out.values():
        rows.sort(key=lambda x: (_i(x.get("event"), 10**6), str(x.get("kickoff_time") or "")))
    return out


def _price_index(prices: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in prices.get("players") or []:
        eid = _i(row.get("element_id", row.get("element")))
        if eid > 0:
            out[eid] = row
    return out


def _fresh_market(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    state = str(row.get("evidence_state") or row.get("status") or "UNAVAILABLE").upper()
    freshness = _f(row.get("freshness_seconds"), 10**9)
    stale_after = _f(cfg.get("max_predictor_freshness_seconds"), 21600)
    stale = state in {"STALE", "UNAVAILABLE", "SCHEMA_CHANGED", "FIELD_MISSING", "CALIBRATING"} or freshness > stale_after
    direction = str(row.get("direction") or row.get("risk_direction") or "STABLE").upper()
    urgency = str(row.get("model_urgency") or row.get("urgency") or "LOW").upper()
    progress = row.get("current_progress_percent", row.get("official_progress_pct"))
    trajectory = row.get("trajectory") or row.get("trajectory_state")
    eta = row.get("eta_human") or row.get("predicted_change_deadline")
    next_window = row.get("next_official_price_update_at")
    imminent = (not stale) and direction in {"RISE", "FALL"} and urgency in set(cfg.get("material_urgencies") or ["HIGH", "CRITICAL"])
    if stale or direction not in {"RISE", "FALL"}:
        eta_text = "Belum ada estimasi perubahan harga yang cukup reliable."
    elif eta:
        verb = "kenaikan" if direction == "RISE" else "penurunan"
        eta_text = f"Memungkinkan {verb} harga sekitar {eta}, jika trajectory bertahan."
    elif imminent:
        verb = "naik" if direction == "RISE" else "turun"
        eta_text = f"Berpeluang {verb} dalam 1–2 update harga berikutnya."
    else:
        eta_text = "Belum ada estimasi perubahan harga yang cukup reliable."
    return {
        "direction": direction,
        "urgency": urgency,
        "progress_percent": progress,
        "trajectory": trajectory,
        "predicted_player_change_eta": eta,
        "next_official_price_update_window": next_window,
        "eta_narrative_id": eta_text,
        "freshness_seconds": row.get("freshness_seconds"),
        "evidence_state": state,
        "fresh": not stale,
        "imminent": imminent,
        "threshold_crossing_is_not_confirmed_change": True,
    }


def _identity_sanity(
    proj: dict[str, Any],
    official: dict[str, Any] | None,
    fixtures_by_team: dict[int, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not official:
        return proj, {
            "status": "BLOCKED",
            "reason": "OFFICIAL_ELEMENT_ID_MISSING",
            "repaired_fields": [],
            "downstream_projection_trusted": False,
        }
    p = dict(proj)
    official_position = POSITIONS.get(_i(official.get("element_type")))
    official_team = _i(official.get("team"))
    local_team = _i(proj.get("team_id", proj.get("team")))
    local_position = str(proj.get("position") or "")
    hard_mismatch = (
        (official_team > 0 and local_team > 0 and official_team != local_team)
        or (official_position and local_position and official_position != local_position)
    )
    repaired: list[str] = []
    replacements = {
        "name": official.get("web_name") or official.get("first_name"),
        "team_id": official_team,
        "position": official_position,
        "now_cost": official.get("now_cost"),
        "ownership_pct": official.get("selected_by_percent"),
        "status": official.get("status"),
    }
    for key, value in replacements.items():
        if value is not None and p.get(key) != value:
            if key not in {"team_id", "position"} or not hard_mismatch:
                p[key] = value
                repaired.append(key)
    p["official_fixture_context"] = (fixtures_by_team.get(official_team) or [])[:5]
    if hard_mismatch:
        return p, {
            "status": "BLOCKED",
            "reason": "IDENTITY_MAPPING_MISMATCH",
            "local_team_id": local_team,
            "official_team_id": official_team,
            "local_position": local_position,
            "official_position": official_position,
            "repaired_fields": repaired,
            "downstream_projection_trusted": False,
        }
    return p, {
        "status": "PASS",
        "reason": None,
        "official_team_id": official_team,
        "official_position": official_position,
        "repaired_fields": repaired,
        "downstream_projection_trusted": True,
    }


def _position_value_percentiles(rows: list[dict[str, Any]]) -> None:
    by_position: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_position.setdefault(str(row.get("position")), []).append(row)
    for items in by_position.values():
        ordered = sorted(items, key=lambda x: _f((x.get("projected_value") or {}).get("xpts5_per_million")))
        n = max(1, len(ordered))
        for idx, row in enumerate(ordered, start=1):
            row.setdefault("projected_value", {})["position_value_percentile"] = round(idx / n, 4)


def build() -> dict[str, Any]:
    cfg = load_policy()
    discovery_cfg = cfg.get("projected_value_market_discovery") or {}
    projections = read_json(DATA / "projections.json", {})
    snapshot = read_json(DATA / "official_snapshot.json", {})
    prices = read_json(DATA / "prices.json", {})
    team = read_json(DATA / "team.json", {})
    owned = {
        _i(row.get("element"))
        for row in (team.get("team_value_ledger") or team.get("squad") or [])
        if _i(row.get("element")) > 0
    }
    official = _official_map(snapshot)
    fixtures_by_team = _fixture_context(snapshot)
    price_map = _price_index(prices)

    rows: list[dict[str, Any]] = []
    blocked_identity: list[dict[str, Any]] = []
    for raw in projections.get("players") or []:
        eid = _i(raw.get("element"))
        if eid <= 0 or eid in owned:
            continue
        p, identity = _identity_sanity(raw, official.get(eid), fixtures_by_team)
        if identity["status"] != "PASS":
            blocked_identity.append({"element": eid, "name": p.get("name"), **identity})
            continue
        xmins = p.get("xmins") or {}
        h3 = _horizon(p, 3)
        h5 = _horizon(p, 5)
        h10 = _horizon(p, 10)
        h15 = _horizon(p, 15)
        price_m = max(_f(p.get("now_cost")) / 10.0, 0.1)
        value = h5 / price_m
        market = _fresh_market(price_map.get(eid) or {}, discovery_cfg)
        start = _f(xmins.get("start_probability"))
        expected_minutes = _f(xmins.get("expected_minutes"))
        status_ok = str(p.get("status") or "") in set(cfg.get("emerging_screen", {}).get("allowed_statuses") or ["a", "d"])

        football_edge = (
            status_ok
            and start >= _f(discovery_cfg.get("football_min_start_probability"), 0.60)
            and expected_minutes >= _f(discovery_cfg.get("football_min_expected_minutes"), 60)
            and h5 >= _f(discovery_cfg.get("football_min_h5"), 14.0)
        )
        structural_edge = (
            status_ok
            and start >= _f(discovery_cfg.get("structural_min_start_probability"), 0.65)
            and value >= _f(discovery_cfg.get("structural_min_xpts5_per_million"), 2.2)
        )
        row = {
            "element": eid,
            "name": p.get("name"),
            "team_id": p.get("team_id"),
            "position": p.get("position"),
            "status": p.get("status"),
            "now_cost": p.get("now_cost"),
            "official_ownership": p.get("ownership_pct"),
            "identity_sanity": identity,
            "official_fixture_context": p.get("official_fixture_context") or [],
            "xmins": {
                "expected_minutes": xmins.get("expected_minutes"),
                "start_probability": xmins.get("start_probability"),
                "dnp_probability": xmins.get("dnp_probability"),
            },
            "horizons": {"3": h3, "5": h5, "10": h10, "15": h15},
            "projected_value": {
                "xpts5_per_million": round(value, 4),
                "position_value_percentile": None,
            },
            "market": market,
            "routes": {
                "FOOTBALL_EDGE": football_edge,
                "VALUE_MARKET_URGENCY": False,
                "STRUCTURAL_EDGE": structural_edge,
            },
            "mandatory_challenger_review": False,
            "price_only_hype_rejected": False,
            "projection": p,
        }
        rows.append(row)

    _position_value_percentiles(rows)
    mandatory: list[int] = []
    for row in rows:
        pv = row["projected_value"]
        market = row["market"]
        value_material = (
            _f(pv.get("position_value_percentile")) >= _f(discovery_cfg.get("minimum_position_value_percentile"), 0.75)
            and _f(pv.get("xpts5_per_million")) >= _f(discovery_cfg.get("value_min_xpts5_per_million"), 2.4)
            and _f((row.get("xmins") or {}).get("start_probability")) >= _f(discovery_cfg.get("value_min_start_probability"), 0.65)
            and _f((row.get("horizons") or {}).get("5")) >= _f(discovery_cfg.get("value_min_h5"), 12.0)
        )
        route = bool(value_material and market.get("imminent") and market.get("fresh"))
        row["routes"]["VALUE_MARKET_URGENCY"] = route
        row["mandatory_challenger_review"] = route
        row["price_only_hype_rejected"] = bool(market.get("imminent") and not value_material)
        if route:
            mandatory.append(_i(row.get("element")))

    rows.sort(
        key=lambda r: (
            bool(r.get("mandatory_challenger_review")),
            bool((r.get("routes") or {}).get("FOOTBALL_EDGE")),
            bool((r.get("routes") or {}).get("STRUCTURAL_EDGE")),
            _f((r.get("projected_value") or {}).get("position_value_percentile")),
            _f((r.get("horizons") or {}).get("5")),
        ),
        reverse=True,
    )
    material = [row for row in rows if any((row.get("routes") or {}).values())]
    return {
        "schema_version": 1,
        "contract": "V3_CHALLENGER_DISCOVERY_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "owner": "decision.owned_challenger_evaluation",
        "source": "FULL_OFFICIAL_PROJECTION_UNIVERSE",
        "universe_count": len(rows) + len(blocked_identity),
        "eligible_candidate_count": len(rows),
        "material_candidate_count": len(material),
        "mandatory_review_count": len(mandatory),
        "mandatory_review_element_ids": mandatory,
        "blocked_identity_count": len(blocked_identity),
        "blocked_identity": blocked_identity,
        "candidates": material,
        "governance": {
            "full_universe_scanned": True,
            "official_identity_sanity_required": True,
            "position_budget_aware_projected_value": True,
            "market_urgency_changes_timing_not_football_truth": True,
            "price_only_hype_never_auto_transfer": True,
            "stale_predictor_cannot_create_mandatory_review": True,
            "threshold_crossing_is_not_confirmed_change": True,
            "no_player_specific_out_hardcode": True,
        },
    }


def run() -> dict[str, Any]:
    payload = build()
    atomic_json(OUT, payload)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["challenger_discovery"] = "data/challenger_discovery.json"
    latest["challenger_discovery_summary"] = {
        "status": "READY" if not payload.get("blocked_identity_count") else "PARTIAL",
        "universe_count": payload.get("universe_count"),
        "material_candidate_count": payload.get("material_candidate_count"),
        "mandatory_review_count": payload.get("mandatory_review_count"),
        "blocked_identity_count": payload.get("blocked_identity_count"),
    }
    atomic_json(DATA / "latest.json", latest)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
