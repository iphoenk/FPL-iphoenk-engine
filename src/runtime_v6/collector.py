from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "v6" / "source_registry.json"
OUT = ROOT / "data" / "v6"
CURRENT = OUT / "current"
MANIFEST = OUT / "manifest.json"

USER_AGENT = "FPL-iphoenk-engine-v6-data-ingestion/1.0 (+public read-only collector)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert payload.get("engine") == "V6_DATA_INGESTION_ONLY"
    assert (payload.get("policy") or {}).get("data_only") is True
    return payload


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _request(url: str, timeout: float, max_body: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/csv,text/html,application/xhtml+xml,*/*;q=0.8",
            },
        )
        elapsed = round((time.perf_counter() - started) * 1000.0, 3)
        raw = response.content
        kept = raw[:max_body]
        content_type = str(response.headers.get("content-type") or "")
        body_text = kept.decode(response.encoding or "utf-8", errors="replace")
        parsed_json = None
        if "json" in content_type.lower():
            try:
                parsed_json = response.json()
            except ValueError:
                parsed_json = None
        return {
            "status": "AVAILABLE" if 200 <= response.status_code < 400 else "UNAVAILABLE",
            "http_status": response.status_code,
            "url": url,
            "fetched_at": _now(),
            "latency_ms": elapsed,
            "content_type": content_type,
            "content_length_bytes": len(raw),
            "stored_bytes": len(kept),
            "truncated": len(raw) > len(kept),
            "sha256": _sha256(raw),
            "json": parsed_json,
            "body": body_text if parsed_json is None else None,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "status": "UNAVAILABLE",
            "http_status": None,
            "url": url,
            "fetched_at": _now(),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "content_type": None,
            "content_length_bytes": None,
            "stored_bytes": 0,
            "truncated": False,
            "sha256": None,
            "json": None,
            "body": None,
            "error": type(exc).__name__,
        }


def _collect_http(source: dict[str, Any], timeout: float, max_body: int) -> dict[str, Any]:
    rows = [_request(str(url), timeout, max_body) for url in source.get("urls") or []]
    available = [row for row in rows if row.get("status") == "AVAILABLE"]
    if available and len(available) == len(rows):
        status = "AVAILABLE"
    elif available:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"
    return {
        "schema_version": 1,
        "source_id": source["id"],
        "source_name": source.get("name"),
        "kind": source.get("kind"),
        "generated_at": _now(),
        "status": status,
        "critical": bool(source.get("critical")),
        "requests": rows,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "public_read_only": True,
            "auth_bypass_used": False,
            "values_not_invented": True,
        },
    }


def _collect_official(source: dict[str, Any], timeout: float, max_body: int) -> dict[str, Any]:
    payload = _collect_http(source, timeout, max_body)
    by_url = {row.get("url"): row for row in payload.get("requests") or []}
    bootstrap_url = next((u for u in source.get("urls") or [] if "bootstrap-static" in u), None)
    fixtures_url = next((u for u in source.get("urls") or [] if u.rstrip("/").endswith("fixtures")), None)
    status_url = next((u for u in source.get("urls") or [] if "event-status" in u), None)
    payload["official"] = {
        "bootstrap": (by_url.get(bootstrap_url) or {}).get("json") if bootstrap_url else None,
        "fixtures": (by_url.get(fixtures_url) or {}).get("json") if fixtures_url else None,
        "event_status": (by_url.get(status_url) or {}).get("json") if status_url else None,
    }
    return payload


def _collect_price_predictor(source: dict[str, Any], official_payload: dict[str, Any]) -> dict[str, Any]:
    bootstrap = ((official_payload.get("official") or {}).get("bootstrap") or {})
    elements = list(bootstrap.get("elements") or [])
    fields = [str(x) for x in source.get("fields") or []]
    rows = [{key: player.get(key) for key in fields if key in player} for player in elements]
    required = {"price_change_percent", "price_change_projections"}
    covered = sum(1 for row in rows if required.issubset(set(row)))
    status = "AVAILABLE" if rows and covered == len(rows) else ("PARTIAL" if rows else "UNAVAILABLE")
    return {
        "schema_version": 1,
        "source_id": source["id"],
        "source_name": source.get("name"),
        "kind": source.get("kind"),
        "generated_at": _now(),
        "status": status,
        "critical": bool(source.get("critical")),
        "derived_from": "official_fpl.bootstrap",
        "player_count": len(rows),
        "covered_player_count": covered,
        "coverage_ratio": round(covered / len(rows), 6) if rows else 0.0,
        "fields": fields,
        "players": rows,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "source": "OFFICIAL_FPL",
            "ui_scraping": False,
            "auth_required": False,
            "values_not_invented": True,
        },
    }


def _write(source_id: str, payload: dict[str, Any]) -> None:
    CURRENT.mkdir(parents=True, exist_ok=True)
    path = CURRENT / f"{source_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def run() -> dict[str, Any]:
    cfg = _load_config()
    policy = cfg.get("policy") or {}
    timeout = float(policy.get("timeout_seconds") or 20)
    max_body = int(policy.get("max_body_bytes") or 250000)
    workers = int(policy.get("max_workers") or 8)
    sources = list(cfg.get("sources") or [])
    source_map = {row["id"]: row for row in sources}

    started = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}

    official = _collect_official(source_map["official_fpl"], timeout, max_body)
    results["official_fpl"] = official
    results["official_price_predictor"] = _collect_price_predictor(
        source_map["official_price_predictor"], official
    )

    remaining = [
        row for row in sources
        if row["id"] not in {"official_fpl", "official_price_predictor"}
    ]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {
            pool.submit(_collect_http, source, timeout, max_body): source
            for source in remaining
        }
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                results[source["id"]] = future.result()
            except Exception as exc:
                results[source["id"]] = {
                    "schema_version": 1,
                    "source_id": source["id"],
                    "source_name": source.get("name"),
                    "generated_at": _now(),
                    "status": "UNAVAILABLE",
                    "critical": bool(source.get("critical")),
                    "error": type(exc).__name__,
                    "governance": {
                        "data_only": True,
                        "decision_authority": "NONE",
                        "isolated_failure": True,
                        "values_not_invented": True,
                    },
                }

    for source in sources:
        _write(source["id"], results[source["id"]])

    critical_failures = [
        source["id"]
        for source in sources
        if source.get("critical") and results[source["id"]].get("status") != "AVAILABLE"
    ]
    statuses = {source["id"]: results[source["id"]].get("status") for source in sources}
    manifest = {
        "schema_version": 1,
        "engine": "V6_DATA_INGESTION_ONLY",
        "generated_at": _now(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "source_count": len(sources),
        "statuses": statuses,
        "critical_failures": critical_failures,
        "overall": "RED" if critical_failures else (
            "GREEN" if all(value == "AVAILABLE" for value in statuses.values()) else "AMBER"
        ),
        "files": {source["id"]: f"data/v6/current/{source['id']}.json" for source in sources},
        "governance": {
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "data_only": True,
            "no_cross_source_averaging": True,
            "no_fabrication": True,
            "source_failure_isolated": True,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
