import json

from src.engines import dss_watchlist


def _projection(element, name, position, element_type, team_id, h5, price=60):
    return {
        "element": element,
        "name": name,
        "team": f"Team {team_id}",
        "team_id": team_id,
        "position": position,
        "element_type": element_type,
        "now_cost": price,
        "status": "a",
        "ownership_pct": 5.0,
        "projection_confidence": "MEDIUM",
        "current_season": {"starts": 1, "minutes": 90},
        "historical_prior": {
            "start_probability": 0.82,
            "minutes": 2100,
            "identity_match": "stable_player_code",
        },
        "xmins": {
            "expected_minutes": 75.0,
            "start_probability": 0.86,
            "bench_probability": 0.09,
            "dnp_probability": 0.05,
        },
        "rates": {
            "xg90": 0.20,
            "xa90": 0.14,
            "bonus90": 0.15,
            "dc90": 0.20,
            "saves90": 0.0,
            "sources": {
                "xg90": "observed_shrunk_to_historical_player_prior+position_prior",
                "xa90": "observed_shrunk_to_historical_player_prior+position_prior",
            },
        },
        "horizons": {
            "3": {"mean": h5 * 0.60, "std": 3.0},
            "5": {"mean": h5, "std": 4.0},
            "10": {"mean": h5 * 2.0, "std": 6.0},
            "15": {"mean": h5 * 3.0, "std": 8.0},
        },
        "xpts_by_gw": [],
    }


def _framework():
    core = dss_watchlist.load_core_registry()["modules"]
    ext = dss_watchlist.load_extension_registry()["modules"]
    return {
        "dss_core": {
            "items": [{"id": row["id"], "status": "ACTIVE"} for row in core]
        },
        "dss_extensions": {
            "items": [{"id": row["id"], "status": "ACTIVE"} for row in ext]
        },
    }


def test_full_dss_watchlist_screens_universe_excludes_owned_and_caps_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(dss_watchlist, "DATA", tmp_path)
    monkeypatch.setattr(dss_watchlist, "OUT", tmp_path / "dss_watchlist.json")

    owned = [
        _projection(1, "Owned GK", "GK", 1, 1, 15.0, 45),
        _projection(2, "Owned DEF", "DEF", 2, 2, 18.0, 50),
        _projection(3, "Owned MID", "MID", 3, 3, 20.0, 65),
        _projection(4, "Owned FWD", "FWD", 4, 4, 21.0, 70),
    ]
    external = [
        _projection(101, "Watch GK", "GK", 1, 5, 19.0, 50),
        _projection(102, "Watch DEF", "DEF", 2, 6, 24.0, 55),
        _projection(103, "Watch MID", "MID", 3, 7, 27.0, 70),
        _projection(104, "Watch FWD", "FWD", 4, 8, 28.0, 75),
    ]
    (tmp_path / "projections.json").write_text(json.dumps({"planning_gw": 2, "players": owned + external}))
    (tmp_path / "team.json").write_text(json.dumps({
        "team_value_ledger": [
            {"element": p["element"], "sell_cost": p["now_cost"]} for p in owned
        ]
    }))
    packages = []
    for p in external:
        packages.append({
            "id": f"1:->{p['element']}", "changes": 1, "legal": True,
            "ins": [{"element": p["element"], "name": p["name"], "now_cost": p["now_cost"]}],
            "affordability": {"resulting_itb": 0},
            "score": {"valid": True, "robust_score": 105.0},
        })
    (tmp_path / "package_optimizer.json").write_text(json.dumps({
        "hold": {"score": {"robust_score": 100.0}}, "packages": packages
    }))
    (tmp_path / "prices.json").write_text(json.dumps({"players": []}))
    (tmp_path / "price_alerts.json").write_text(json.dumps({"alerts": []}))
    (tmp_path / "framework_health.json").write_text(json.dumps(_framework()))

    out = dss_watchlist.build()
    assert out["status"] == "READY"
    assert out["screening_contract"] == "FULL_DSS_SCREEN_V1"
    assert out["screening_audit"]["full_registry_traversal"] is True
    assert out["screening_audit"]["dss_core"]["traversed"] == 50
    assert out["screening_audit"]["dss_extensions"]["traversed"] == 16
    assert sum(len(rows) for rows in out["positions"].values()) == 4
    assert not ({1, 2, 3, 4} & {row["element"] for rows in out["positions"].values() for row in rows})
    for position, rows in out["positions"].items():
        assert len(rows) <= 5
        for row in rows:
            assert row["position"] == position
            assert row["admitted"] is True
            assert row["action"] == "WATCH"
            assert row["lifecycle"] == "NEW"
            assert row["evidence_coverage"] >= 0.70
            assert row["dimensions"]["set_piece_penalty"]["status"] == "MISSING"
            assert "evidence set-piece/penalty belum cukup" in row["risks"]


def test_critical_dss_failure_blocks_watchlist_publication(monkeypatch, tmp_path):
    monkeypatch.setattr(dss_watchlist, "DATA", tmp_path)
    monkeypatch.setattr(dss_watchlist, "OUT", tmp_path / "dss_watchlist.json")
    p = _projection(101, "Candidate", "MID", 3, 5, 25.0, 70)
    (tmp_path / "projections.json").write_text(json.dumps({"planning_gw": 2, "players": [p]}))
    (tmp_path / "team.json").write_text(json.dumps({"team_value_ledger": []}))
    (tmp_path / "package_optimizer.json").write_text(json.dumps({"hold": {"score": {"robust_score": 0}}, "packages": []}))
    (tmp_path / "prices.json").write_text(json.dumps({"players": []}))
    (tmp_path / "price_alerts.json").write_text(json.dumps({"alerts": []}))
    framework = _framework()
    framework["dss_core"]["items"][0]["status"] = "FAILED"
    (tmp_path / "framework_health.json").write_text(json.dumps(framework))

    out = dss_watchlist.build()
    assert out["status"] == "BLOCKED"
    assert out["screening_summary"]["published_candidates"] == 0
    assert out["screening_audit"]["critical_framework_failure_blocks_publication"] is True


def test_lifecycle_labels_are_deterministic():
    previous = {10: ("MID", 3), 11: ("MID", 1)}
    assert dss_watchlist._lifecycle(99, "MID", 1, previous) == "NEW"
    assert dss_watchlist._lifecycle(10, "MID", 2, previous) == "UP"
    assert dss_watchlist._lifecycle(11, "MID", 2, previous) == "DOWN"
    assert dss_watchlist._lifecycle(10, "MID", 3, previous) == "KEEP"
