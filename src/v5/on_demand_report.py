from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.v5.config_cache import load_json_config

REGISTRY = "config/v5_on_demand_report_registry.json"


def _load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _name(row: Any) -> str | None:
    return str(row.get("name")) if isinstance(row, dict) and row.get("name") else None


def _lineup_names(lineup: dict[str, Any]) -> list[str]:
    return [str(row.get("name")) for row in lineup.get("starting_xi") or [] if isinstance(row, dict) and row.get("name")]


def _bench_names(lineup: dict[str, Any]) -> list[str]:
    rows = lineup.get("bench") or lineup.get("bench_order") or []
    return [str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name")]


def build(source_dir: str, output_dir: str, request_config: str, source_sha: str) -> dict[str, Any]:
    src = Path(source_dir)
    out = Path(output_dir)
    registry = load_json_config(REGISTRY)
    trigger = _load(Path(request_config), {}) or {}
    latest = _load(src / "latest.json", {}) or {}
    user = _load(src / "user_report.json", {}) or {}
    lineup = _load(src / "lineup_decision.json", {}) or {}
    decision_brief = _load(src / "decision_brief.json", {}) or {}
    framework = _load(src / "framework_health.json", {}) or {}
    watchlist_summary = _load(src / "dss_watchlist_summary.json", {}) or {}

    if not latest or not user or not lineup:
        raise RuntimeError("on-demand report requires fresh latest, user_report and lineup_decision artifacts")
    owned = user.get("owned_squad") if isinstance(user.get("owned_squad"), dict) else {}
    owned_facts = owned.get("facts") if isinstance(owned.get("facts"), list) else []
    price = user.get("price_radar") if isinstance(user.get("price_radar"), dict) else {}
    decision = user.get("decision") if isinstance(user.get("decision"), dict) else {}
    captaincy = user.get("captaincy") if isinstance(user.get("captaincy"), dict) else {}
    chip = user.get("chip") if isinstance(user.get("chip"), dict) else {}
    external = user.get("external_watchlist") if isinstance(user.get("external_watchlist"), dict) else {}
    phase = latest.get("phase") if isinstance(latest.get("phase"), dict) else {}
    generated_at = str(latest.get("generated_at") or lineup.get("generated_at") or datetime.now(timezone.utc).isoformat())
    packaged_at = datetime.now(timezone.utc).isoformat()

    quick_view = {
        "overall": decision.get("overall"),
        "squad_decision": decision.get("squad"),
        "xi_decision": decision.get("starting_xi"),
        "captaincy_decision": decision.get("captaincy"),
        "chip_decision": decision.get("chip"),
        "price_decision": decision.get("price"),
        "confidence": decision.get("confidence"),
        "owned_count": int(owned.get("count") or len(owned_facts)),
        "formation": lineup.get("formation"),
        "starting_xi": _lineup_names(lineup),
        "bench": _bench_names(lineup),
        "captain": _name(lineup.get("captain")) or ((captaincy.get("facts") or {}).get("model_candidate") if isinstance(captaincy.get("facts"), dict) else None),
        "vice_captain": _name(lineup.get("vice_captain")) or ((captaincy.get("facts") or {}).get("vice_candidate") if isinstance(captaincy.get("facts"), dict) else None),
        "captaincy_confidence": captaincy.get("confidence"),
        "active_chip": ((chip.get("facts") or {}).get("active_chip") if isinstance(chip.get("facts"), dict) else None),
        "owned_price_alerts": price.get("owned") or [],
        "external_price_alerts": price.get("external_watchlist") or price.get("external") or [],
        "watchlist_count": int(external.get("count") or external.get("candidate_count") or watchlist_summary.get("count") or 0),
        "watchlist_status": external.get("status") or watchlist_summary.get("status"),
    }

    payload = {
        "schema_version": 1,
        "report_type": "ON_DEMAND_TEAM_SNAPSHOT",
        "model": registry.get("model_id"),
        "request": {
            "request_id": trigger.get("request_id"),
            "requested_at": trigger.get("requested_at"),
            "requested_by": trigger.get("requested_by"),
            "request_note": trigger.get("request_note"),
        },
        "authority": {
            "strategy": registry.get("authority_strategy"),
            "engine_track": "V3_PRODUCTION",
            "engine_version": latest.get("engine_version"),
            "source_branch": registry.get("production_source_branch"),
            "source_sha": source_sha,
            "production_authoritative": True,
            "v5_beta_overlay_used": False,
        },
        "freshness": {
            "engine_generated_at": generated_at,
            "packaged_at": packaged_at,
            "target_minutes": registry.get("freshness_target_minutes"),
            "fresh_run": True,
        },
        "context": {
            "phase": phase.get("phase"),
            "planning_gw": phase.get("planning_gw"),
            "scoring_gw": phase.get("scoring_gw"),
            "deadline_time": phase.get("deadline_time"),
            "squad_authority": latest.get("squad_authority") or lineup.get("squad_authority"),
        },
        "quick_view": quick_view,
        "user_report": user,
        "lineup_decision": lineup,
        "decision_brief": decision_brief,
        "framework_health_summary": {
            "overall": framework.get("overall") or framework.get("status"),
            "go_allowed": framework.get("go_allowed"),
            "recommendation_allowed": framework.get("recommendation_allowed"),
        },
        "governance": {
            "read_only_report": True,
            "auto_submit_fpl_changes": False,
            "v5_auto_promotion": False,
        },
    }

    request_id = str(trigger.get("request_id") or packaged_at.replace(":", "").replace("+00:00", "Z"))
    safe_id = "".join(ch for ch in request_id if ch.isalnum() or ch in {"-", "_", "."}) or "request"
    _atomic_write(out / "latest.json", payload)
    _atomic_write(out / "reports" / f"{safe_id}.json", payload)
    print(json.dumps({
        "report_type": payload["report_type"],
        "engine_version": payload["authority"]["engine_version"],
        "generated_at": generated_at,
        "formation": quick_view["formation"],
        "captain": quick_view["captain"],
        "owned_count": quick_view["owned_count"],
        "watchlist_count": quick_view["watchlist_count"],
        "output": str(out / "latest.json"),
    }, ensure_ascii=False))
    return payload


def cli() -> None:
    parser = argparse.ArgumentParser(description="Package a fresh production-authoritative on-demand FPL team report")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-dir", default="data/on_demand")
    parser.add_argument("--request-config", default="config/v5_on_demand_trigger.json")
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    build(args.source_dir, args.output_dir, args.request_config, args.source_sha)


if __name__ == "__main__":
    cli()
