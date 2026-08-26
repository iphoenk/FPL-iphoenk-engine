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
    assert watch.get("public_contract", {}).get("user_report_positions_are_public_safe") is True
    assert watch.get("public_contract", {}).get("technical_candidate_evidence_moved_to_candidate_audit") is True
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
    target_owned = int(policy.get("owned_target") or 15)
    target_total = int(policy.get("target_total") or 20)
    target_per_position = int(policy.get("target_per_position") or policy.get("max_per_position") or 5)
    assert len(owned) == target_owned, ("owned_count", len(owned), target_owned)

    candidate_audit = watch.get("candidate_audit") or {}
    published = set()
    position_counts = {}
    for position in policy.get("positions") or []:
        rows = (watch.get("positions") or {}).get(position) or []
        position_counts[position] = len(rows)
        assert len(rows) == target_per_position, (position, len(rows), target_per_position)
        assert len(rows) <= int(policy.get("max_per_position") or 5), (position, len(rows))
        for expected_rank, row in enumerate(rows, start=1):
            element = int(row["element"])
            technical = candidate_audit.get(str(element)) or {}
            assert element not in owned
            assert element not in published
            published.add(element)
            assert row.get("position") == position
            assert int(row.get("rank") or -1) == expected_rank
            assert row.get("action") == "WATCH"
            assert row.get("lifecycle") in allowed_lifecycle - {"REMOVE"}
            assert float(row.get("evidence_coverage") or 0) >= min_coverage
            assert len(row.get("reasons") or []) >= 1
            assert row.get("dss_score") is not None
            assert technical.get("admitted") is True
            assert set((technical.get("dimensions") or {}).keys()) == required
            assert "dimensions" not in row
            assert "package_context" not in row
            assert "rejection_reasons" not in row
            assert "sources" not in (row.get("underlying") or {})
            assert "official_projection_health" not in (row.get("price_risk") or {})

    summary = watch.get("screening_summary") or {}
    assert int(summary.get("projection_players") or 0) >= 500
    assert int(summary.get("published_candidates") or 0) == len(published)
    assert len(published) == target_total, ("watchlist_total", len(published), target_total)
    assert len(candidate_audit) == len(published)
    assert watch.get("governance", {}).get("price_is_overlay_not_primary_reason") is True
    assert latest.get("files", {}).get("dss_watchlist") == "data/dss_watchlist.json"
    assert latest.get("dss_watchlist_summary", {}).get("status") == "READY"
    assert latest.get("dss_watchlist_summary", {}).get("full_registry_traversal") is True
    assert latest.get("dss_watchlist_summary", {}).get("public_sanitized") is True

    user_watch = user.get("external_watchlist") or {}
    assert user_watch.get("status") == "READY", user_watch
    serialized_user_watch = json.dumps(user_watch, ensure_ascii=False)
    for token in ("SUSPECT_STATIC_OFFSET0", "DSS-", "go_allowed", "package_id", "position_prior"):
        assert token not in serialized_user_watch, token
    for position, rows in (user_watch.get("positions") or {}).items():
        assert [int(row["element"]) for row in rows] == [int(row["element"]) for row in (watch.get("positions") or {}).get(position, [])]

    result = {
        "status": "PASS",
        "owned": len(owned),
        "published": len(published),
        "position_counts": position_counts,
        "core_traversed": (audit.get("dss_core") or {}).get("traversed"),
        "extensions_traversed": (audit.get("dss_extensions") or {}).get("traversed"),
        "public_safe": True,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
