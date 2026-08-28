from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"refusing blind edit; block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---- source adapter: extend the existing Vaastav owner, no second historical source ----
vaastav = ROOT / "src/sources/vaastav.py"
replace_once(
    vaastav,
    '''def previous_season():\n    """Return vaastav's short label for the season before the configured one."""\n    configured = str(_cfg().get("season", "2026-2027"))\n    try:\n        start = int(configured[:4]) - 1\n    except (TypeError, ValueError):\n        start = 2025\n    return f"{start}-{str(start + 1)[-2:]}"\n\n\n''',
    '''def season_before(offset: int = 1):\n    """Return Vaastav's short label for a completed season before the configured season."""\n    configured = str(_cfg().get("season", "2026-2027"))\n    try:\n        start = int(configured[:4]) - int(offset)\n    except (TypeError, ValueError):\n        start = 2026 - int(offset)\n    return f"{start}-{str(start + 1)[-2:]}"\n\n\ndef previous_season():\n    return season_before(1)\n\n\ndef historical_seasons(depth: int | None = None):\n    """Older completed seasons used only as a bounded fallback behind last season."""\n    configured_depth = int((_cfg().get("vaastav") or {}).get("historical_depth", 2))\n    count = max(0, int(configured_depth if depth is None else depth))\n    return [season_before(offset) for offset in range(2, 2 + count)]\n\n\n''',
)
old_previous = '''def sync_previous_season():\n    """Fetch a dedicated prior-season snapshot, never a current-season fallback."""\n    season = previous_season()\n    last_error = None\n    for filename in ("players_raw.csv", "cleaned_players.csv"):\n        url = f"{_base()}/{season}/{filename}"\n        try:\n            rows = _fetch_csv(url)\n            if not rows:\n                raise RuntimeError("empty CSV")\n            columns = set(rows[0])\n            required = {"first_name", "second_name", "minutes"}\n            if not required.issubset(columns):\n                raise RuntimeError(f"schema missing required columns: {sorted(required - columns)}")\n            payload = {\n                "source": "vaastav/Fantasy-Premier-League",\n                "season": season,\n                "fetched_at": iso_now(),\n                "available_at": iso_now(),\n                "source_url": url,\n                "row_count": len(rows),\n                "data_mode": "PREVIOUS_SEASON_SNAPSHOT",\n                "status": "LIVE",\n                "schema_columns": sorted(columns),\n                "rows": rows,\n            }\n            CACHE.mkdir(parents=True, exist_ok=True)\n            atomic_json(CACHE / "vaastav_previous_season.json", payload)\n            return payload\n        except Exception as exc:\n            last_error = f"{type(exc).__name__}: {exc}"\n    failure = {\n        "source": "vaastav/Fantasy-Premier-League",\n        "season": season,\n        "fetched_at": iso_now(),\n        "status": "FAILED",\n        "error": last_error,\n    }\n    CACHE.mkdir(parents=True, exist_ok=True)\n    atomic_json(CACHE / "vaastav_previous_season_error.json", failure)\n    return failure\n'''
new_previous = '''def _sync_completed_season(season: str, outfile: str, data_mode: str):\n    """Fetch or reuse an immutable completed-season snapshot from the canonical Vaastav adapter."""\n    CACHE.mkdir(parents=True, exist_ok=True)\n    path = CACHE / outfile\n    cached = read_json(path, {})\n    if cached.get("status") == "LIVE" and cached.get("season") == season and cached.get("rows"):\n        return {**cached, "cache_reused": True}\n\n    last_error = None\n    for filename in ("players_raw.csv", "cleaned_players.csv"):\n        url = f"{_base()}/{season}/{filename}"\n        try:\n            rows = _fetch_csv(url)\n            if not rows:\n                raise RuntimeError("empty CSV")\n            columns = set(rows[0])\n            required = {"first_name", "second_name", "minutes", "code", "starts"}\n            if not required.issubset(columns):\n                raise RuntimeError(f"schema missing required columns: {sorted(required - columns)}")\n            payload = {\n                "source": "vaastav/Fantasy-Premier-League",\n                "season": season,\n                "fetched_at": iso_now(),\n                "available_at": iso_now(),\n                "source_url": url,\n                "row_count": len(rows),\n                "data_mode": data_mode,\n                "status": "LIVE",\n                "schema_columns": sorted(columns),\n                "immutable_completed_season": True,\n                "rows": rows,\n            }\n            atomic_json(path, payload)\n            return payload\n        except Exception as exc:\n            last_error = f"{type(exc).__name__}: {exc}"\n    failure = {\n        "source": "vaastav/Fantasy-Premier-League",\n        "season": season,\n        "fetched_at": iso_now(),\n        "status": "FAILED",\n        "error": last_error,\n    }\n    atomic_json(CACHE / f"{path.stem}_error.json", failure)\n    return failure\n\n\ndef sync_previous_season():\n    return _sync_completed_season(\n        previous_season(),\n        "vaastav_previous_season.json",\n        "PREVIOUS_SEASON_SNAPSHOT",\n    )\n\n\ndef sync_historical_season(season: str):\n    if season not in historical_seasons():\n        raise ValueError(f"historical season outside configured depth: {season}")\n    safe = season.replace("-", "_")\n    return _sync_completed_season(\n        season,\n        f"vaastav_historical_{safe}.json",\n        "HISTORICAL_SEASON_SNAPSHOT",\n    )\n'''
replace_once(vaastav, old_previous, new_previous)

# ---- enrichment: fetch older completed seasons in parallel with existing enrichments ----
enrichment = ROOT / "src/services/enrichment_service.py"
replace_once(
    enrichment,
    '''    advanced = {}\n    if sync_stats and stats_gw:\n        tasks = {\n            "core_insights": lambda: core_insights.sync_gw(stats_gw),\n            "vaastav": lambda: vaastav.sync_gw(stats_gw),\n            "last_season": vaastav.sync_previous_season,\n        }\n        if deep_stats:\n            tasks["deep"] = lambda: core_insights.sync_optional_deep_files(stats_gw)\n        results = _run_parallel(tasks)\n        advanced = {\n            "core_insights": {"ok": bool(results["core_insights"].get("schema_valid")), "rows": results["core_insights"].get("row_count")},\n            "vaastav": {"ok": bool(results["vaastav"].get("rows")), "rows": results["vaastav"].get("row_count")},\n            "last_season": {"ok": bool(results["last_season"].get("rows")), "rows": results["last_season"].get("row_count")},\n        }\n        if deep_stats:\n            advanced["deep"] = results["deep"]\n''',
    '''    advanced = {}\n    if sync_stats and stats_gw:\n        history_seasons = vaastav.historical_seasons()\n        tasks = {\n            "core_insights": lambda: core_insights.sync_gw(stats_gw),\n            "vaastav": lambda: vaastav.sync_gw(stats_gw),\n            "last_season": vaastav.sync_previous_season,\n        }\n        for season in history_seasons:\n            tasks[f"historical:{season}"] = lambda season=season: vaastav.sync_historical_season(season)\n        if deep_stats:\n            tasks["deep"] = lambda: core_insights.sync_optional_deep_files(stats_gw)\n        results = _run_parallel(tasks)\n        advanced = {\n            "core_insights": {"ok": bool(results["core_insights"].get("schema_valid")), "rows": results["core_insights"].get("row_count")},\n            "vaastav": {"ok": bool(results["vaastav"].get("rows")), "rows": results["vaastav"].get("row_count")},\n            "last_season": {"ok": bool(results["last_season"].get("rows")), "rows": results["last_season"].get("row_count")},\n            "historical_seasons": {\n                season: {\n                    "ok": bool(results[f"historical:{season}"].get("rows")),\n                    "rows": results[f"historical:{season}"].get("row_count"),\n                    "cache_reused": bool(results[f"historical:{season}"].get("cache_reused")),\n                }\n                for season in history_seasons\n            },\n        }\n        if deep_stats:\n            advanced["deep"] = results["deep"]\n''',
)

# ---- prediction inputs: aggregate older seasons by stable player identity ----
inputs = ROOT / "src/models/v4_prediction_inputs.py"
insert_after = '''def build_last_season_index(elements, payload):\n'''
text = inputs.read_text(encoding="utf-8")
start = text.index(insert_after)
load_marker = '\n\ndef load_prediction_enrichment(elements, stats_gw=None):\n'
load_index = text.index(load_marker, start)
historical_func = '''\n\ndef build_historical_index(elements, payloads):\n    """Aggregate two-or-more older completed seasons for bounded fallback priors."""\n    valid_payloads = [\n        payload for payload in (payloads or [])\n        if payload.get("status") == "LIVE" and payload.get("season") and payload.get("rows")\n    ]\n    valid_payloads.sort(key=lambda payload: str(payload.get("season")), reverse=True)\n    season_indexes = [\n        (str(payload["season"]), build_last_season_index(elements, payload))\n        for payload in valid_payloads\n    ]\n    result = {}\n    for player in elements:\n        element = int(player["id"])\n        observations = []\n        for rank, (season, index) in enumerate(season_indexes):\n            row = index.get(element)\n            if not row:\n                continue\n            minutes = max(0.0, f(row.get("minutes")))\n            recency = 0.65 ** rank\n            reliability = min(1.0, minutes / 1800.0)\n            weight = recency * (0.35 + 0.65 * reliability)\n            observations.append((season, row, weight))\n        if not observations:\n            continue\n        total_weight = sum(weight for _, _, weight in observations)\n        if total_weight <= 0:\n            continue\n        result[element] = {\n            "minutes": sum(f(row.get("minutes")) for _, row, _ in observations),\n            "starts": sum(f(row.get("starts")) for _, row, _ in observations),\n            "xg_per90": sum(f(row.get("xg_per90")) * weight for _, row, weight in observations) / total_weight,\n            "xa_per90": sum(f(row.get("xa_per90")) * weight for _, row, weight in observations) / total_weight,\n            "start_rate": sum(f(row.get("start_rate")) * weight for _, row, weight in observations) / total_weight,\n            "avg_minutes_when_start": sum(f(row.get("avg_minutes_when_start")) * weight for _, row, weight in observations) / total_weight,\n            "seasons_used": [season for season, _, _ in observations],\n            "season_count": len(observations),\n            "source": "+".join(f"vaastav:{season}" for season, _, _ in observations),\n            "identity_matches": [row.get("identity_match") for _, row, _ in observations],\n            "aggregation": "recency_and_minutes_weighted_older_seasons",\n        }\n    return result\n'''
inputs.write_text(text[:load_index] + historical_func + text[load_index:], encoding="utf-8")
replace_once(
    inputs,
    '''    previous = read_json(DATA / "stats" / "vaastav_previous_season.json", {})\n    return {\n        "advanced": aggregate_advanced(core.get("rows"), shots.get("rows"), matches.get("rows")),\n        "last_season": build_last_season_index(elements, previous),\n        "meta": {\n            "stats_gw": stats_gw,\n            "advanced_files": [name for name, obj in (("core_insights", core), ("shots", shots), ("playermatchstats", matches)) if obj.get("rows")],\n            "last_season": previous.get("season"),\n        },\n    }\n''',
    '''    previous = read_json(DATA / "stats" / "vaastav_previous_season.json", {})\n    historical_payloads = [\n        read_json(path, {})\n        for path in sorted((DATA / "stats").glob("vaastav_historical_*.json"), reverse=True)\n    ]\n    historical_payloads = [payload for payload in historical_payloads if payload.get("status") == "LIVE"]\n    historical = build_historical_index(elements, historical_payloads)\n    return {\n        "advanced": aggregate_advanced(core.get("rows"), shots.get("rows"), matches.get("rows")),\n        "last_season": build_last_season_index(elements, previous),\n        "historical": historical,\n        "meta": {\n            "stats_gw": stats_gw,\n            "advanced_files": [name for name, obj in (("core_insights", core), ("shots", shots), ("playermatchstats", matches)) if obj.get("rows")],\n            "last_season": previous.get("season"),\n            "historical_seasons": [str(payload.get("season")) for payload in historical_payloads],\n            "historical_source": "vaastav/Fantasy-Premier-League",\n        },\n    }\n''',
)

# ---- prediction owner: bounded fallback only when immediate last-season evidence is thin ----
runner = ROOT / "src/engines/v4_runner.py"
replace_once(
    runner,
    '''def player_priors(player, last_season=None):\n    pos = int(player.get("element_type", 3))\n    price = f(player.get("now_cost")) / 10\n    ownership = f(player.get("selected_by_percent"))\n    creativity = f(player.get("creativity"))\n    threat = f(player.get("threat"))\n    premium = clamp((price - 6.0) / 9.5)\n    role = clamp((ownership / 35) * 0.25 + (threat / 100) * 0.45 + (creativity / 100) * 0.30)\n    base_xg = XG_PRIOR[pos] * (1 + 0.75 * premium + 0.35 * role)\n    base_xa = XA_PRIOR[pos] * (1 + 0.45 * premium + 0.45 * role)\n    prior_weight = min(0.65, f((last_season or {}).get("minutes")) / 1800 * 0.65)\n    xg = base_xg * (1 - prior_weight) + f((last_season or {}).get("xg_per90"), base_xg) * prior_weight\n    xa = base_xa * (1 - prior_weight) + f((last_season or {}).get("xa_per90"), base_xa) * prior_weight\n    return {\n        "xg90_prior": xg,\n        "xa90_prior": xa,\n        "premium_prior": premium,\n        "role_prior": role,\n        "last_season_weight": prior_weight,\n        "last_season_minutes": f((last_season or {}).get("minutes")),\n        "last_season_source": (last_season or {}).get("source"),\n        "last_season_identity_match": (last_season or {}).get("identity_match"),\n    }\n''',
    '''def player_priors(player, last_season=None, historical=None):\n    pos = int(player.get("element_type", 3))\n    price = f(player.get("now_cost")) / 10\n    ownership = f(player.get("selected_by_percent"))\n    creativity = f(player.get("creativity"))\n    threat = f(player.get("threat"))\n    premium = clamp((price - 6.0) / 9.5)\n    role = clamp((ownership / 35) * 0.25 + (threat / 100) * 0.45 + (creativity / 100) * 0.30)\n    base_xg = XG_PRIOR[pos] * (1 + 0.75 * premium + 0.35 * role)\n    base_xa = XA_PRIOR[pos] * (1 + 0.45 * premium + 0.45 * role)\n    last_minutes = f((last_season or {}).get("minutes"))\n    prior_weight = min(0.65, last_minutes / 1800 * 0.65)\n    history_minutes = f((historical or {}).get("minutes"))\n    history_seasons = list((historical or {}).get("seasons_used") or [])\n    thin_last_season = clamp((900.0 - last_minutes) / 900.0)\n    historical_weight = (\n        min(0.25, history_minutes / 3600 * 0.25) * thin_last_season\n        if len(history_seasons) >= 2 else 0.0\n    )\n    historical_weight = min(historical_weight, max(0.0, 0.75 - prior_weight))\n    base_weight = max(0.0, 1 - prior_weight - historical_weight)\n    xg = (\n        base_xg * base_weight\n        + f((last_season or {}).get("xg_per90"), base_xg) * prior_weight\n        + f((historical or {}).get("xg_per90"), base_xg) * historical_weight\n    )\n    xa = (\n        base_xa * base_weight\n        + f((last_season or {}).get("xa_per90"), base_xa) * prior_weight\n        + f((historical or {}).get("xa_per90"), base_xa) * historical_weight\n    )\n    return {\n        "xg90_prior": xg,\n        "xa90_prior": xa,\n        "premium_prior": premium,\n        "role_prior": role,\n        "last_season_weight": prior_weight,\n        "last_season_minutes": last_minutes,\n        "last_season_source": (last_season or {}).get("source"),\n        "last_season_identity_match": (last_season or {}).get("identity_match"),\n        "historical_weight": historical_weight,\n        "historical_minutes": history_minutes,\n        "historical_seasons": history_seasons,\n        "historical_source": (historical or {}).get("source"),\n        "historical_prior_consumed": historical_weight > 0,\n        "historical_usage": "thin_or_missing_last_season_fallback_only",\n    }\n''',
)
replace_once(
    runner,
    '''    advanced = enrichment["advanced"]\n    last_season = enrichment["last_season"]\n    quality = _quality_config()\n''',
    '''    advanced = enrichment["advanced"]\n    last_season = enrichment["last_season"]\n    historical = enrichment.get("historical") or {}\n    quality = _quality_config()\n''',
)
replace_once(
    runner,
    '''    materially_distinct = 0\n    advanced_decision_used = 0\n    for player in elements:\n        priors = player_priors(player, last_season.get(player["id"]))\n''',
    '''    materially_distinct = 0\n    advanced_decision_used = 0\n    historical_fallback_consumed = 0\n    for player in elements:\n        priors = player_priors(player, last_season.get(player["id"]), historical.get(player["id"]))\n        historical_fallback_consumed += int(bool(priors.get("historical_prior_consumed")))\n''',
)
replace_once(
    runner,
    '''            "last_season_weight": priors["last_season_weight"],\n            "last_season_source": priors["last_season_source"],\n            "set_piece_share": role["set_piece_share"],\n''',
    '''            "last_season_weight": priors["last_season_weight"],\n            "last_season_source": priors["last_season_source"],\n            "historical_weight": priors["historical_weight"],\n            "historical_source": priors["historical_source"],\n            "historical_seasons": priors["historical_seasons"],\n            "historical_prior_consumed": priors["historical_prior_consumed"],\n            "set_piece_share": role["set_piece_share"],\n''',
)
replace_once(
    runner,
    '''            "last_season_matched": len(last_season),\n            **enrichment["meta"],\n''',
    '''            "last_season_matched": len(last_season),\n            "historical_matched": len(historical),\n            "historical_fallback_consumed": historical_fallback_consumed,\n            **enrichment["meta"],\n''',
)
replace_once(
    runner,
    '''            "advanced_decision_coverage": advanced_decision_used,\n        },\n''',
    '''            "advanced_decision_coverage": advanced_decision_used,\n            "historical_fallback_consumed": historical_fallback_consumed,\n        },\n''',
)

# ---- per-fixture provenance exposes the historical fallback without duplicating scoring ----
model = ROOT / "src/models/v4_prediction.py"
replace_once(
    model,
    '''            "last_season_weight": round(f(ctx.get("last_season_weight")), 4),\n            "opponent_defence_resistance": round(opponent_defence, 4),\n''',
    '''            "last_season_weight": round(f(ctx.get("last_season_weight")), 4),\n            "historical_weight": round(f(ctx.get("historical_weight")), 4),\n            "historical_prior_consumed": bool(ctx.get("historical_prior_consumed")),\n            "opponent_defence_resistance": round(opponent_defence, 4),\n''',
)
replace_once(
    model,
    '''            "last_season_source": ctx.get("last_season_source"),\n            "set_piece_source": ctx.get("set_piece_source"),\n''',
    '''            "last_season_source": ctx.get("last_season_source"),\n            "historical_source": ctx.get("historical_source"),\n            "historical_seasons": ctx.get("historical_seasons") or [],\n            "historical_prior_consumed": bool(ctx.get("historical_prior_consumed")),\n            "set_piece_source": ctx.get("set_piece_source"),\n''',
)

# ---- health: prove two older seasons and actual decision-path consumption ----
health = ROOT / "src/engines/framework_health_audit.py"
anchor = '''def _probe_learning_loop() -> tuple[str, dict]:\n'''
text = health.read_text(encoding="utf-8")
idx = text.index(anchor)
historical_probe = '''def _probe_historical_prior() -> tuple[bool, dict]:\n    obj = read_json(DATA / "predictions_v4.json", {})\n    coverage = obj.get("input_coverage") or {}\n    players = list(obj.get("players") or [])\n    seasons = list(coverage.get("historical_seasons") or [])\n    consumed_rows = [\n        row for row in players\n        if (row.get("priors") or {}).get("historical_prior_consumed") is True\n        and float((row.get("priors") or {}).get("historical_weight") or 0) > 0\n        and len((row.get("priors") or {}).get("historical_seasons") or []) >= 2\n    ]\n    ok = (\n        len(seasons) >= 2\n        and int(coverage.get("historical_matched") or 0) > 0\n        and int(coverage.get("historical_fallback_consumed") or 0) == len(consumed_rows)\n        and len(consumed_rows) > 0\n    )\n    return ok, {\n        "source": coverage.get("historical_source"),\n        "seasons": seasons,\n        "historical_matched": coverage.get("historical_matched"),\n        "fallback_consumed_players": len(consumed_rows),\n        "usage": "thin_or_missing_last_season_fallback_only",\n        "canonical_owner": "src.models.v4_prediction_inputs.build_historical_index + src.engines.v4_runner.player_priors",\n    }\n\n\n'''
health.write_text(text[:idx] + historical_probe + text[idx:], encoding="utf-8")
replace_once(
    health,
    '''        "last_season_integration": _probe_last_season,\n        "defcon_rules": _probe_defcon,\n''',
    '''        "last_season_integration": _probe_last_season,\n        "historical_prior": _probe_historical_prior,\n        "defcon_rules": _probe_defcon,\n''',
)
replace_once(
    health,
    '''        "preseason_prior", "historical_prior", "regression_risk",\n''',
    '''        "preseason_prior", "regression_risk",\n''',
)

# ---- DSS registry: remove unrelated report-history file as DSS-36 evidence ----
registry = ROOT / "config/dss_core_registry.json"
obj = json.loads(registry.read_text(encoding="utf-8"))
row36 = next(row for row in obj.get("modules", []) if row.get("id") == "DSS-36")
row36["required_files"] = ["data/predictions_v4.json"]
registry.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---- source config controls depth; no hidden hard-coded production depth ----
sources = ROOT / "config/sources.json"
source_obj = json.loads(sources.read_text(encoding="utf-8"))
source_obj.setdefault("vaastav", {})["historical_depth"] = 2
sources.write_text(json.dumps(source_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---- prediction contract + ownership make evidence and reuse mandatory ----
contracts = ROOT / "config/service_contract_registry.json"
contract_obj = json.loads(contracts.read_text(encoding="utf-8"))
required = contract_obj["contracts"]["predictions"].setdefault("required_paths", [])
for path in (
    "input_coverage.historical_seasons",
    "input_coverage.historical_matched",
    "input_coverage.historical_fallback_consumed",
    "capability_evidence.historical_fallback_consumed",
):
    if path not in required:
        required.append(path)
contracts.write_text(json.dumps(contract_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

ownership = ROOT / "config/architecture_ownership_registry.json"
ownership_obj = json.loads(ownership.read_text(encoding="utf-8"))
shared = ownership_obj.setdefault("shared_primitives", [])
entry = {
    "id": "MULTI_SEASON_HISTORICAL_PRIOR",
    "owner": "prediction_model",
    "implementation": "src.models.v4_prediction_inputs.build_historical_index + src.engines.v4_runner.player_priors",
    "consumers": ["DSS-36"],
}
if not any(row.get("id") == entry["id"] for row in shared):
    shared.append(entry)
ownership.write_text(json.dumps(ownership_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---- quality gate: DSS-36 must be real, consumed, and still leave calibration warmup truthful ----
quality = ROOT / "src/engines/v4_quality_gate.py"
replace_once(
    quality,
    '''    assert core["DSS-16"]["status"] == "ACTIVE", core["DSS-16"]\n    assert core["DSS-29"]["status"] == "ACTIVE", core["DSS-29"]\n''',
    '''    assert core["DSS-16"]["status"] == "ACTIVE", core["DSS-16"]\n    assert core["DSS-29"]["status"] == "ACTIVE", core["DSS-29"]\n    assert core["DSS-36"]["status"] == "ACTIVE", core["DSS-36"]\n''',
)
replace_once(
    quality,
    '''    assert coverage.get("last_season_matched", 0) > 0\n    assert coverage.get("advanced_decision_used_ratio", 0) >= 0.25\n''',
    '''    assert coverage.get("last_season_matched", 0) > 0\n    assert len(coverage.get("historical_seasons") or []) >= 2\n    assert coverage.get("historical_matched", 0) > 0\n    assert coverage.get("historical_fallback_consumed", 0) > 0\n    assert coverage.get("advanced_decision_used_ratio", 0) >= 0.25\n''',
)

# ---- focused tests, all offline ----
test = ROOT / "tests/test_v4963_multiseason_prior.py"
test.write_text('''from src.engines.v4_runner import player_priors\nfrom src.models.v4_prediction_inputs import build_historical_index\nfrom src.sources.vaastav import historical_seasons\n\n\ndef _player():\n    return {\n        "id": 1, "code": 999, "element_type": 3, "now_cost": 70,\n        "selected_by_percent": "5.0", "creativity": "20", "threat": "30",\n        "first_name": "Test", "second_name": "Player",\n    }\n\n\ndef _payload(season, minutes, xg90, xa90):\n    return {\n        "status": "LIVE", "season": season,\n        "rows": [{\n            "code": "999", "first_name": "Test", "second_name": "Player",\n            "minutes": str(minutes), "starts": "20",\n            "expected_goals_per_90": str(xg90), "expected_assists_per_90": str(xa90),\n        }],\n    }\n\n\ndef test_historical_seasons_exclude_immediate_previous_season():\n    seasons = historical_seasons(depth=2)\n    assert seasons == ["2024-25", "2023-24"]\n\n\ndef test_multi_season_index_requires_and_preserves_multiple_older_seasons():\n    out = build_historical_index([_player()], [\n        _payload("2024-25", 1800, 0.4, 0.2),\n        _payload("2023-24", 1500, 0.2, 0.1),\n    ])\n    row = out[1]\n    assert row["season_count"] == 2\n    assert row["seasons_used"] == ["2024-25", "2023-24"]\n    assert 0.2 < row["xg_per90"] < 0.4\n    assert row["aggregation"] == "recency_and_minutes_weighted_older_seasons"\n\n\ndef test_historical_prior_only_supplements_thin_last_season():\n    history = {\n        "minutes": 3300, "xg_per90": 0.35, "xa_per90": 0.18,\n        "seasons_used": ["2024-25", "2023-24"], "source": "vaastav:2024-25+vaastav:2023-24",\n    }\n    thin = player_priors(_player(), {"minutes": 180, "xg_per90": 0.5, "xa_per90": 0.2, "source": "vaastav:2025-26"}, history)\n    assert thin["historical_prior_consumed"] is True\n    assert thin["historical_weight"] > 0\n    assert thin["last_season_weight"] > 0\n\n    strong = player_priors(_player(), {"minutes": 1800, "xg_per90": 0.5, "xa_per90": 0.2, "source": "vaastav:2025-26"}, history)\n    assert strong["historical_prior_consumed"] is False\n    assert strong["historical_weight"] == 0\n\n\ndef test_historical_prior_is_used_when_last_season_missing():\n    history = {\n        "minutes": 3300, "xg_per90": 0.35, "xa_per90": 0.18,\n        "seasons_used": ["2024-25", "2023-24"], "source": "vaastav:2024-25+vaastav:2023-24",\n    }\n    priors = player_priors(_player(), None, history)\n    assert priors["last_season_weight"] == 0\n    assert priors["historical_prior_consumed"] is True\n    assert priors["historical_weight"] > 0\n''', encoding="utf-8")

readme = ROOT / "README.md"
readme_text = readme.read_text(encoding="utf-8")
heading = "## V4.9.6 multi-season historical prior closeout"
if heading not in readme_text:
    readme_text += f'''\n\n{heading}\n\n- DSS-36 Multi-Season / Historical Prior uses the existing Vaastav adapter to cache two older completed seasons (2024-25 and 2023-24 for the current 2026-27 configuration).\n- Immediate previous season (DSS-35) remains the primary historical prior. Older multi-season evidence is consumed only as a bounded fallback when the immediate previous-season sample is thin or missing, preventing double counting.\n- Historical identity matching reuses the existing stable player-code / unique-full-name resolver; the prediction model owns aggregation and prior blending, while health only verifies evidence and decision-path consumption.\n- Completed-season caches are immutable/reusable, so routine checkpoints do not repeatedly refetch historical seasons once a valid cache is present.\n'''
    readme.write_text(readme_text, encoding="utf-8")

print(json.dumps({"status": "staged", "target": "DSS-36", "historical_depth": 2}))
