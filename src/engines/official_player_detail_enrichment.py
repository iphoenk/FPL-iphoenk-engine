from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.engines.official_snapshot_primitives import load_snapshot
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, iso_now

PROFILE = os.getenv("FPL_EXECUTION_PROFILE", "fast_decision").strip() or "fast_decision"
DEFAULT_BATCH = {
    "fast_decision": 0,
    "live": 0,
    "full_refresh": 160,
    "deep_stats": 623,
}
MAX_WORKERS = max(1, min(12, int(os.getenv("FPL_ELEMENT_SUMMARY_WORKERS", "8"))))


def _load(name: str, default: Any) -> Any:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixtures": payload.get("fixtures") or [],
        "history": payload.get("history") or [],
        "history_past": payload.get("history_past") or [],
    }


def _batch_limit(total: int) -> int:
    override = os.getenv("FPL_ELEMENT_SUMMARY_UNIVERSE_MAX")
    if override is not None:
        try:
            return max(0, min(total, int(override)))
        except (TypeError, ValueError):
            pass
    return min(total, DEFAULT_BATCH.get(PROFILE, 0))


def _targets(universe_ids: list[int], cached_ids: set[int], cursor: int, limit: int) -> tuple[list[int], int, str]:
    if not universe_ids or limit <= 0:
        return [], cursor, "CACHE_ONLY_PROFILE"

    missing = [eid for eid in universe_ids if eid not in cached_ids]
    if missing:
        selected = missing[:limit]
        return selected, cursor, "MISSING_FIRST"

    start = cursor % len(universe_ids)
    rotated = universe_ids[start:] + universe_ids[:start]
    selected = rotated[:limit]
    next_cursor = (start + len(selected)) % len(universe_ids)
    return selected, next_cursor, "ROTATING_REFRESH"


def _fetch_many(element_ids: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    payloads: dict[str, Any] = {}
    health: dict[str, Any] = {}
    if not element_ids:
        return payloads, health

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(element_ids)), thread_name_prefix="official-player-detail") as pool:
        futures = {pool.submit(get_json, f"element-summary/{eid}/", retries=1): eid for eid in element_ids}
        for future in as_completed(futures):
            eid = futures[future]
            try:
                payload, row = future.result()
            except Exception as exc:
                payload = None
                row = {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
            health[str(eid)] = row
            if isinstance(payload, dict):
                payloads[str(eid)] = _compact(payload)
    return payloads, health


def run() -> dict[str, Any]:
    detail = _load("official_detail.json", {})
    latest = _load("latest.json", {})
    snapshot = load_snapshot(DATA)
    bootstrap = snapshot.get("bootstrap") or {}
    elements = [row for row in (bootstrap.get("elements") or []) if isinstance(row, dict) and row.get("id") is not None]
    universe_ids = sorted({int(row["id"]) for row in elements})

    previous = detail.get("element_summaries") if isinstance(detail.get("element_summaries"), dict) else {}
    cached: dict[str, Any] = dict(previous)
    cached_ids = {int(key) for key in cached if str(key).isdigit()}
    prior_meta = detail.get("player_detail_enrichment") if isinstance(detail.get("player_detail_enrichment"), dict) else {}
    cursor = int(prior_meta.get("refresh_cursor") or 0)
    limit = _batch_limit(len(universe_ids))
    targets, next_cursor, selection_mode = _targets(universe_ids, cached_ids, cursor, limit)

    fetched, fetch_health = _fetch_many(targets)
    cached.update(fetched)

    total = len(universe_ids)
    covered = sum(1 for eid in universe_ids if str(eid) in cached)
    live = sum(1 for row in fetch_health.values() if isinstance(row, dict) and row.get("status") == "LIVE")
    failed = len(targets) - len(fetched)

    if total == 0:
        evidence_state = "UNAVAILABLE_WITH_SAFE_FALLBACK"
    elif covered >= total:
        evidence_state = "AVAILABLE"
    elif covered > 0:
        evidence_state = "PARTIAL"
    else:
        evidence_state = "UNAVAILABLE_WITH_SAFE_FALLBACK"

    meta = {
        "schema_version": 1,
        "contract": "OFFICIAL_PLAYER_DETAIL_ENRICHMENT_V1",
        "generated_at": iso_now(),
        "profile": PROFILE,
        "evidence_state": evidence_state,
        "universe_players": total,
        "cached_players": covered,
        "coverage_ratio": round(covered / total, 4) if total else 0.0,
        "selection_mode": selection_mode,
        "batch_limit": limit,
        "refresh_cursor": next_cursor,
        "current_refresh": {
            "requested": len(targets),
            "live": live,
            "payloads_received": len(fetched),
            "failed_or_unavailable": failed,
        },
        "health": fetch_health,
        "governance": {
            "classification": "OPTIONAL_PUBLIC_ENRICHMENT",
            "decision_blocking": False,
            "partial_data_is_usable": True,
            "missing_data_is_not_zero": True,
            "missing_external_evidence_fabricated": False,
            "failed_refresh_preserves_last_known_good_player_detail": True,
            "fast_and_live_profiles_do_not_fan_out_element_summary_network_calls": True,
            "full_refresh_collects_missing_players_first": True,
            "deep_stats_may_refresh_full_universe": True,
            "core_official_identity_and_legality_remain_separate_required_authority": True,
        },
    }

    detail["element_summaries"] = cached
    detail["player_detail_enrichment"] = meta
    atomic_json(DATA / "official_detail.json", detail)

    summary = latest.setdefault("official_detail_summary", {})
    summary["player_detail_enrichment"] = {
        "evidence_state": evidence_state,
        "coverage": f"{covered}/{total}",
        "coverage_ratio": meta["coverage_ratio"],
        "profile": PROFILE,
        "current_refresh_requested": len(targets),
        "current_refresh_live": live,
        "decision_blocking": False,
    }
    atomic_json(DATA / "latest.json", latest)
    return meta


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
