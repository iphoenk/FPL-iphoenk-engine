from __future__ import annotations

import json

from src.utils import DATA, ROOT


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict:
    health = _load(DATA / "source_health.json")
    registry = _load(ROOT / "config" / "sources" / "registry.json")
    observations = _load(DATA / "challenger_observations.json")

    registry_sources = {row["id"]: row for row in registry.get("sources") or []}
    runtime_sources = {row["id"]: row for row in health.get("sources") or []}
    enabled = {source_id for source_id, row in registry_sources.items() if row.get("enabled") is True}

    assert (health.get("registry") or {}).get("integrity_ok") is True
    assert enabled <= set(runtime_sources), ("missing_runtime_sources", sorted(enabled - set(runtime_sources)))
    assert health.get("critical_failed") == [], health.get("critical_failed")

    official = runtime_sources["official_fpl"]
    assert official.get("status") == "LIVE"
    assert official.get("reachable") is True
    for state in (official.get("capabilities") or {}).values():
        assert state == "AUTHORITATIVE_NATIVE", state

    onefpl = runtime_sources["onefpl"]
    onefpl_detail = onefpl.get("detail") or {}
    onefpl_price = (onefpl.get("capabilities") or {}).get("price_prediction")
    assert onefpl_detail.get("parser_version") == "onefpl-price-v2"
    assert onefpl_detail.get("no_fabrication") is True
    assert onefpl_detail.get("source_reachability_separate") is True
    assert isinstance(onefpl_detail.get("attempts"), list)
    assert any(row.get("role") == "reachability_probe" for row in onefpl_detail["attempts"])
    assert any(str(row.get("role", "")).startswith("structured_") for row in onefpl_detail["attempts"])

    if onefpl.get("reachable") is True:
        assert onefpl.get("status") == "LIVE"
        if int(onefpl.get("observation_count") or 0) > 0:
            assert onefpl_price == "AVAILABLE"
            assert onefpl_detail.get("data_values_ingested") is True
            assert onefpl_detail.get("selected_structured_url")
        else:
            assert onefpl_price in {
                "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION",
                "SOURCE_REACHABLE_STRUCTURED_ACCESS_RESTRICTED",
            }, onefpl_price
            assert onefpl_detail.get("data_values_ingested") is False
    else:
        assert onefpl.get("status") == "UNAVAILABLE"
        assert onefpl_price == "UNAVAILABLE"

    rows = observations.get("observations") or []
    for row in rows:
        assert row.get("contract") == "challenger_observation_v2"
        assert row.get("provider") in {"livefpl", "onefpl"}
        assert row.get("value") is not None
        assert row.get("source_url")
        assert row.get("fetched_at")
        assert row.get("observed_at")

    result = {
        "status": "PASS",
        "source_overall": health.get("overall"),
        "decision_blocking": health.get("decision_blocking"),
        "onefpl": {
            "status": onefpl.get("status"),
            "reachable": onefpl.get("reachable"),
            "price_data_state": onefpl_price,
            "observations": onefpl.get("observation_count"),
            "primary_structured_http_status": onefpl_detail.get("primary_structured_http_status"),
            "structured_http_status": onefpl_detail.get("structured_http_status"),
            "selected_structured_url": onefpl_detail.get("selected_structured_url"),
            "fallback_used": onefpl_detail.get("structured_fallback_used"),
        },
        "challenger_observations": len(rows),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
