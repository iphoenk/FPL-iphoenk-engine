from __future__ import annotations

import json
from pathlib import Path

from src.utils import DATA, ROOT

REGISTRY = ROOT / "config" / "report_artifact_registry.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _watch_ids(positions: dict) -> list[int]:
    return [int(row["element"]) for rows in positions.values() for row in rows]


def run() -> dict:
    registry = _load(REGISTRY)
    contract = registry["consumer_contract"]
    expected_owned = int(contract["owned_count"])
    expected_watch = int(contract["watchlist_total"])
    expected_per = int(contract["watchlist_per_position"])
    positions = list(contract["watchlist_positions"])

    brief = _load(DATA / "decision_brief.json")
    deep = _load(DATA / "deep_review_payload.json")
    user = _load(DATA / "user_report.json")
    summary = _load(DATA / "dss_watchlist_summary.json")
    latest = _load(DATA / "latest.json")

    owned = brief.get("owned_15") or []
    assert len(owned) == expected_owned, ("brief_owned", len(owned), expected_owned)
    owned_ids = {int(x["element"]) for x in owned}
    assert len(owned_ids) == expected_owned

    for payload_name, watch_positions in (
        ("brief", brief.get("watchlist_20") or {}),
        ("deep", deep.get("watchlist_20") or {}),
        ("user", ((user.get("external_watchlist") or {}).get("positions") or {})),
        ("summary", summary.get("positions") or {}),
    ):
        assert set(watch_positions) == set(positions), (payload_name, sorted(watch_positions))
        for position in positions:
            rows = watch_positions.get(position) or []
            assert len(rows) == expected_per, (payload_name, position, len(rows), expected_per)
            assert all(row.get("position") == position for row in rows), (payload_name, position)
        ids = _watch_ids(watch_positions)
        assert len(ids) == expected_watch and len(set(ids)) == expected_watch, (payload_name, len(ids), len(set(ids)))
        assert not (owned_ids & set(ids)), (payload_name, sorted(owned_ids & set(ids)))

    assert len(((user.get("owned_squad") or {}).get("facts") or [])) == expected_owned
    assert (user.get("serving_contract") or {}).get("owned") == expected_owned
    assert (user.get("serving_contract") or {}).get("watchlist") == expected_watch
    assert (brief.get("serving_contract") or {}).get("owned") == expected_owned
    assert (brief.get("serving_contract") or {}).get("watchlist") == expected_watch

    files = latest.get("files") or {}
    assert files.get("decision_brief") == "data/decision_brief.json"
    assert files.get("deep_review_payload") == "data/deep_review_payload.json"
    assert files.get("dss_watchlist_summary") == "data/dss_watchlist_summary.json"
    assert latest.get("report_serving", {}).get("owned_count") == expected_owned
    assert latest.get("report_serving", {}).get("watchlist_count") == expected_watch

    sizes = {}
    for name, spec in (registry.get("artifacts") or {}).items():
        path_text = str(spec.get("path") or "")
        if not path_text.startswith("data/"):
            continue
        path = DATA / path_text.removeprefix("data/")
        if not path.exists():
            continue
        sizes[name] = path.stat().st_size
        if spec.get("priority") == "P0" and spec.get("max_bytes") is not None:
            assert sizes[name] <= int(spec["max_bytes"]), (name, sizes[name], spec["max_bytes"])

    result = {
        "status": "PASS",
        "owned": expected_owned,
        "watchlist": expected_watch,
        "per_position": expected_per,
        "sizes": sizes,
        "default_fast": latest.get("report_serving", {}).get("default_fast_artifact"),
        "default_deep": latest.get("report_serving", {}).get("default_deep_review_artifact"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
