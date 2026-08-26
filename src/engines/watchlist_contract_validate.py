from __future__ import annotations

import json

from src.utils import DATA, ROOT


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict:
    watch = _load(DATA / "dss_watchlist.json")
    latest = _load(DATA / "latest.json")
    user = _load(DATA / "user_report.json")
    policy = _load(ROOT / "config" / "intelligence" / "dss_watchlist.json")
    team = _load(DATA / "team.json")

    assert watch.get("model") == "full_dss_watchlist_v1"
    assert watch.get("screening_contract") == "FULL_DSS_SCREEN_V1"
    assert watch.get("status") == "READY", watch.get("screening_summary")
    audit = watch.get("screening_audit") or {}
    assert audit.get("full_registry_traversal") is True
    assert (audit.get("dss_core") or {}).get("declared") == 50
    assert (audit.get("dss_core") or {}).get("traversed") == 50
    assert (audit.get("dss_extensions") or {}).get("declared") == 16
    assert (audit.get("dss_extensions") or {}).get("traversed") == 16
    assert not (audit.get("dss_core") or {}).get("critical_failed")

    required = set((policy.get("dimension_weights") or {}).keys())
    allowed_lifecycle = set(((policy.get("lifecycle") or {}).get("labels") or []))
    min_coverage = float(((policy.get("admission") or {}).get("minimum_dimension_coverage") or 0))
    owned = {int(row.get("element") or -1) for row in team.get("team_value_ledger") or []}
    published = set()
    position_counts = {}
    for position in policy.get("positions") or []:
        rows = (watch.get("positions") or {}).get(position) or []
        position_counts[position] = len(rows)
        assert 1 <= len(rows) <= int(policy.get("max_per_position") or 5), (position, len(rows))
        for expected_rank, row in enumerate(rows, start=1):
            element = int(row["element"])
            assert element not in owned
            assert element not in published
            published.add(element)
            assert row.get("position") == position
            assert int(row.get("rank") or -1) == expected_rank
            assert row.get("admitted") is True
            assert row.get("action") == "WATCH"
            assert row.get("lifecycle") in allowed_lifecycle - {"REMOVE"}
            assert float(row.get("evidence_coverage") or 0) >= min_coverage
            assert set((row.get("dimensions") or {}).keys()) == required
            assert len(row.get("reasons") or []) >= 1
            assert row.get("dss_score") is not None

    summary = watch.get("screening_summary") or {}
    assert int(summary.get("projection_players") or 0) >= 500
    assert int(summary.get("published_candidates") or 0) == len(published)
    assert len(published) <= 20
    assert watch.get("governance", {}).get("price_is_overlay_not_primary_reason") is True
    assert latest.get("files", {}).get("dss_watchlist") == "data/dss_watchlist.json"
    assert latest.get("dss_watchlist_summary", {}).get("status") == "READY"
    assert latest.get("dss_watchlist_summary", {}).get("full_registry_traversal") is True

    user_watch = user.get("external_watchlist") or {}
    assert user_watch.get("status") == "READY", user_watch
    for position, rows in (user_watch.get("positions") or {}).items():
        assert [int(row["element"]) for row in rows] == [int(row["element"]) for row in (watch.get("positions") or {}).get(position, [])]

    result = {
        "status": "PASS",
        "published": len(published),
        "position_counts": position_counts,
        "core_traversed": (audit.get("dss_core") or {}).get("traversed"),
        "extensions_traversed": (audit.get("dss_extensions") or {}).get("traversed"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
