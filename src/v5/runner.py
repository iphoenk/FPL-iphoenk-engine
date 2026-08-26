from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from src.utils import iso_now
from src.v5 import V5_VERSION
from src.v5.authenticated_official import collect_runtime, safe_finance
from src.v5.config_cache import load_json_config
from src.v5.event_context import EventContext, build_event_context
from src.v5.identity import build_index
from src.v5.live_scoring import personalized_live_score
from src.v5.official_auth import expected_team_id
from src.v5.performance import PipelineTimer
from src.v5.persistence import read_artifact, write_artifact, write_snapshot
from src.v5.prediction_bridge import build_predictions
from src.v5.price_service import build_price_snapshot
from src.v5.public_api import FetchSpec, fetch_many
from src.v5.team_service import build_team_state

RUNNER_CONFIG = "config/v5_runner_registry.json"
SQUAD_CONFIG = "config/v5_squad_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(RUNNER_CONFIG)
    if not isinstance(data.get("pipeline"), list):
        raise RuntimeError("invalid V5 runner registry")
    return data


def _resolve_token(value: Any, tokens: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in tokens:
            raise KeyError(f"missing V5 runner token: {key}")
        return tokens[key]
    return value


def _request_specs(section: str, tokens: dict[str, Any]) -> dict[str, FetchSpec]:
    raw_section = _cfg().get(section)
    if not isinstance(raw_section, dict):
        raise RuntimeError(f"invalid V5 runner request section: {section}")
    specs = {}
    for name, raw in raw_section.items():
        if not isinstance(raw, dict):
            continue
        when = raw.get("when")
        if when and not tokens.get(str(when)):
            continue
        params = {
            str(key): _resolve_token(value, tokens)
            for key, value in (raw.get("params") or {}).items()
        }
        specs[str(name)] = FetchSpec(route=str(raw["route"]), params=params)
    return specs


def _locked_squad() -> dict:
    squad_cfg = load_json_config(SQUAD_CONFIG)
    return load_json_config(str(squad_cfg["locked_squad_config"]))


def _event_dict(context: EventContext) -> dict[str, Any]:
    return {
        "current_gw": context.current_gw,
        "next_gw": context.next_gw,
        "last_finished_gw": context.last_finished_gw,
        "planning_gw": context.planning_gw,
        "submitted_gw": context.submitted_gw,
        "scoring_gw": context.scoring_gw,
        "deadline_time": context.deadline_time,
        "is_live_event": context.is_live_event,
        "phase": context.phase.value,
    }


def _scope_auth_summary(runtime: dict[str, Any], owned_ids: list[int]) -> dict[str, Any]:
    summary = dict(runtime.get("summary") or {})
    my_team = runtime.get("my_team") if isinstance(runtime.get("my_team"), dict) else None
    summary["safe_finance"] = safe_finance(my_team, owned_ids) if my_team else {}
    draft = {
        int(row["element"])
        for row in (my_team or {}).get("picks", []) or []
        if row.get("element") is not None
    }
    integrity = dict(summary.get("draft_integrity") or {})
    integrity["matches_authoritative_squad"] = draft == set(owned_ids) if draft else None
    summary["draft_integrity"] = integrity
    return summary


def assemble_snapshot(
    *,
    mode: str,
    base_payloads: dict[str, Any],
    base_health: dict[str, dict] | None = None,
    dynamic_payloads: dict[str, Any] | None = None,
    dynamic_health: dict[str, dict] | None = None,
    auth_runtime: dict[str, Any] | None = None,
    locked_squad: dict | None = None,
    previous_price_state: dict | None = None,
    predictions: dict | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    bootstrap = base_payloads.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise RuntimeError("V5 FAIL CLOSED: bootstrap unavailable")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated_at = current_time.isoformat()
    context = build_event_context(bootstrap, now=current_time)
    dynamic = dynamic_payloads or {}
    runtime = auth_runtime or {"summary": {"state": "DISABLED"}, "my_team": None}
    identity = build_index(bootstrap)
    team = build_team_state(
        phase=context.phase,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=locked_squad,
        authenticated_my_team=runtime.get("my_team"),
        submitted_picks=dynamic.get("submitted_picks"),
        transfers=base_payloads.get("entry_transfers") if isinstance(base_payloads.get("entry_transfers"), list) else [],
        entry=base_payloads.get("entry") if isinstance(base_payloads.get("entry"), dict) else None,
    )
    owned_ids = [int(x) for x in team["owned_ids"]]
    auth_summary = _scope_auth_summary(runtime, owned_ids)
    live = personalized_live_score(
        picks=dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None,
        event_live=dynamic.get("event_live") if isinstance(dynamic.get("event_live"), dict) else None,
        identity=identity,
        scoring_gw=context.scoring_gw,
        is_live_event=context.is_live_event,
    )
    price_bundle = build_price_snapshot(
        bootstrap,
        previous_state=previous_price_state or {},
        owned_ids=owned_ids,
        now=current_time,
    )
    prediction_payload = predictions or {
        "status": "NOT_BUILT",
        "players": [],
        "v5_bridge": {"enabled": False},
    }
    public_health = {**(base_health or {}), **(dynamic_health or {})}
    limits = _cfg()["summary_limits"]
    snapshot = {
        "schema_version": int(_cfg()["snapshot"]["schema_version"]),
        "engine_version": V5_VERSION,
        "runner_status": _cfg()["status"],
        "generated_at": generated_at,
        "mode": mode,
        "team_id": expected_team_id(),
        "phase": _event_dict(context),
        "squad_authority": team["authority"],
        "team_summary": {
            "bank": team["finance"].get("bank"),
            "market_value": team["finance"].get("market_value"),
            "sell_value": team["finance"].get("sell_value"),
            "sell_value_complete": team["finance"].get("sell_value_complete"),
            "finance_exact_count": team["finance"].get("exact_count"),
            "unresolved_sell_values": team["finance"].get("unresolved_elements"),
        },
        "live_summary": {
            "status": live.get("status"),
            "gross_points": live.get("gross_points"),
            "net_points": live.get("net_points"),
        },
        "price_summary": {
            "confirmed_changes": price_bundle["prices"].get("confirmed_changes", []),
            "top_rise_risk": price_bundle["prices"].get("top_rise_risk", [])[: int(limits["price_rise_risk"])],
            "top_fall_risk": price_bundle["prices"].get("top_fall_risk", [])[: int(limits["price_fall_risk"])],
            "alerts": price_bundle["alerts"].get("alerts", [])[: int(limits["price_alerts"])],
        },
        "prediction_summary": {
            "status": prediction_payload.get("status", "BUILT"),
            "model_version": prediction_payload.get("model_version"),
            "player_count": len(prediction_payload.get("players", []) or []),
            "v5_bridge": prediction_payload.get("v5_bridge", {}),
        },
        "endpoint_health": public_health,
        "authenticated_official": auth_summary,
        "governance": {
            "production_promotion_allowed": bool(_cfg()["snapshot"].get("production_promotion_allowed", False)),
            "pipeline": list(_cfg()["pipeline"]),
            "raw_authenticated_payload_persisted": False,
        },
    }
    return {
        "snapshot": snapshot,
        "team": team,
        "live": live,
        "prices": price_bundle["prices"],
        "price_trajectory": price_bundle["trajectory_state"],
        "price_alerts": price_bundle["alerts"],
        "predictions": prediction_payload,
        "context": context,
    }


def run(mode: str | None = None, *, persist: bool = True, include_predictions: bool = True) -> dict[str, Any]:
    timer = PipelineTimer()
    cfg = _cfg()
    selected_mode = mode or str(cfg["default_mode"])
    if selected_mode not in set(str(x) for x in cfg["modes"]):
        raise ValueError(f"unsupported V5 runner mode: {selected_mode}")
    team_id = expected_team_id()
    tokens = {"team_id": team_id}

    with timer.stage("public_base_collection"):
        base_payloads, base_health = fetch_many(_request_specs("base_requests", tokens))
    bootstrap = base_payloads.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise RuntimeError("V5 FAIL CLOSED: bootstrap unavailable")

    with timer.stage("event_context"):
        context = build_event_context(bootstrap)
    tokens.update({
        "submitted_gw": context.submitted_gw,
        "scoring_gw": context.scoring_gw,
        "planning_gw": context.planning_gw,
    })
    dynamic_specs = _request_specs("dynamic_requests", tokens)

    with timer.stage("dynamic_and_authenticated_collection"):
        workers = int(cfg["concurrency"]["max_orchestration_workers"])
        if cfg["concurrency"].get("parallelize_dynamic_and_authenticated_collection", True):
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                dynamic_future = pool.submit(fetch_many, dynamic_specs)
                if cfg.get("feature_switches", {}).get("authenticated_overlay", True):
                    auth_future = pool.submit(collect_runtime, ())
                else:
                    auth_future = None
                dynamic_payloads, dynamic_health = dynamic_future.result()
                auth_runtime = auth_future.result() if auth_future else {"summary": {"state": "DISABLED"}, "my_team": None}
        else:
            dynamic_payloads, dynamic_health = fetch_many(dynamic_specs)
            auth_runtime = collect_runtime(()) if cfg.get("feature_switches", {}).get("authenticated_overlay", True) else {
                "summary": {"state": "DISABLED"},
                "my_team": None,
            }

    previous_price_state = read_artifact("price_trajectory", {}) if cfg.get("feature_switches", {}).get("price_trajectory", True) else {}
    lock = _locked_squad()

    predictions = None
    if include_predictions and cfg.get("feature_switches", {}).get("v4_prediction_bridge", True):
        with timer.stage("prediction_bridge"):
            stats_gw = context.current_gw or context.last_finished_gw
            predictions = build_predictions(
                bootstrap,
                base_payloads.get("fixtures") if isinstance(base_payloads.get("fixtures"), list) else [],
                iso_now(),
                stats_gw=stats_gw,
            )

    with timer.stage("assemble_runtime"):
        result = assemble_snapshot(
            mode=selected_mode,
            base_payloads=base_payloads,
            base_health=base_health,
            dynamic_payloads=dynamic_payloads,
            dynamic_health=dynamic_health,
            auth_runtime=auth_runtime,
            locked_squad=lock,
            previous_price_state=previous_price_state,
            predictions=predictions,
        )

    result["snapshot"]["performance"] = timer.report()
    if persist and cfg.get("feature_switches", {}).get("persistence", True):
        with timer.stage("persistence"):
            write_artifact("health", {
                "generated_at": result["snapshot"]["generated_at"],
                "public": result["snapshot"]["endpoint_health"],
                "authenticated": result["snapshot"]["authenticated_official"].get("endpoint_health", {}),
            })
            write_artifact("team", result["team"])
            write_artifact("live", result["live"])
            write_artifact("prices", result["prices"])
            write_artifact("price_trajectory", result["price_trajectory"])
            write_artifact("price_alerts", result["price_alerts"])
            write_artifact("predictions", result["predictions"])
        result["snapshot"]["performance"] = timer.report()
        gw = result["context"].submitted_gw or result["context"].planning_gw
        result["snapshot"]["files"] = write_snapshot(result["snapshot"], gw=gw)

    return result["snapshot"]


def cli() -> None:
    cfg = _cfg()
    parser = argparse.ArgumentParser(description="FPL iphoenk Engine V5 alpha runner")
    parser.add_argument("mode", choices=tuple(str(x) for x in cfg["modes"]), nargs="?", default=str(cfg["default_mode"]))
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--no-predictions", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.mode, persist=not args.no_persist, include_predictions=not args.no_predictions),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    cli()
