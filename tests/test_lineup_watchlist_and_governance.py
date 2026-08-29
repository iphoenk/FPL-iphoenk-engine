from __future__ import annotations

import json

from src.engines import dss_watchlist, watchlist_public_sanitize
from src.engines.lineup_governance import build_lineup_decision, build_package_decision
import src.engines.dss_operationalization_overlay as operationalization
from src.engines.dss_operationalization_overlay import EVALUATORS, load_policy
from src.models.package_optimizer_v2 import load_config, score_package
from src.rules import LINEUP_RULES


def _projection(element, position, mean, team_id):
    element_type = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "element_type": element_type,
        "team_id": team_id,
        "now_cost": 50,
        "projection_confidence": "MEDIUM",
        "xmins": {
            "start_probability": 0.90,
            "bench_probability": 0.08,
            "dnp_probability": 0.02,
            "expected_minutes": 78,
        },
        "xpts_by_gw": [{"gw": 2, "mean": mean, "std": 1.5, "fixtures": []}],
    }


def _fixtures():
    positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    means = [4.8, 3.2, 5.7, 5.5, 5.3, 4.2, 3.9, 7.8, 7.1, 6.4, 5.8, 4.0, 9.5, 6.7, 6.2]
    projections = [_projection(i + 1, pos, means[i], i + 1) for i, pos in enumerate(positions)]
    lock = {
        "authoritative_phase": "pre_deadline_wc",
        "wildcard_active": True,
        "players": [{"element": i + 1, "position": pos, "purchase_cost": 50} for i, pos in enumerate(positions)],
    }
    return {"planning_gw": 2, "players": projections}, lock


def test_governed_lineup_is_legal_and_has_safe_captaincy():
    projections, lock = _fixtures()
    decision = build_lineup_decision(projections, lock, {"used": []})
    assert decision["formation"] in set(LINEUP_RULES["legal_formations"])
    assert len(decision["starting_xi"]) == 11
    assert sum(p["position"] == "GK" for p in decision["starting_xi"]) == 1
    xi_ids = {p["element"] for p in decision["starting_xi"]}
    assert decision["captain"]["element"] in xi_ids
    assert decision["vice_captain"]["element"] in xi_ids
    assert decision["captain"]["element"] != decision["vice_captain"]["element"]
    assert decision["captain"]["element"] in {p["element"] for p in decision["captain_safe_pool"]}
    assert decision["vice_captain"]["element"] in {p["element"] for p in decision["captain_safe_pool"]}
    assert decision["bench"]["gk"]["position"] == "GK"
    assert len(decision["bench"]["order"]) == 3
    assert decision["main_starting_xi_battle"]["status"] in {"CLOSE", "CLEAR", "NO_ALTERNATIVE"}
    assert decision["chip_context"]["active_chip"] == "wildcard"
    assert decision["chip_context"]["single_chip_rule_respected"] is True


def test_manual_lock_freezes_optimizer_candidate_and_revalidates_gate0():
    projections, lock = _fixtures()
    hold = {"id": "HOLD", "legal": True, "score": {"valid": True}, "changes": 0, "outs": [], "ins": []}
    challenger = {"id": "1:8->99", "legal": True, "score": {"valid": True}, "changes": 1, "outs": [], "ins": []}
    optimizer = {"status": "READY", "hold": hold, "packages": [challenger, hold]}
    decision = build_package_decision(optimizer, projections, lock, {"team_value_ledger": []})
    assert decision["optimizer_best_candidate_id"] == challenger["id"]
    assert decision["selected_package_id"] == "HOLD"
    assert decision["manual_authority_override"] is True
    assert decision["current_squad_legal"] is True
    assert decision["gate0_revalidated"] is True
    assert decision["governance"]["optimizer_is_candidate_generator_only"] is True


def _watch_projection(element, name, position, element_type, team_id, h5, price=60):
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
        "historical_prior": {"start_probability": 0.82, "minutes": 2100, "identity_match": "stable_player_code"},
        "xmins": {"expected_minutes": 75.0, "start_probability": 0.86, "bench_probability": 0.09, "dnp_probability": 0.05},
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
        "dss_core": {"items": [{"id": row["id"], "status": "ACTIVE"} for row in core]},
        "dss_extensions": {"items": [{"id": row["id"], "status": "ACTIVE"} for row in ext]},
    }


def test_full_dss_watchlist_screens_universe_excludes_owned_and_caps_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(dss_watchlist, "DATA", tmp_path)
    monkeypatch.setattr(dss_watchlist, "OUT", tmp_path / "dss_watchlist.json")
    owned = [
        _watch_projection(1, "Owned GK", "GK", 1, 1, 15.0, 45),
        _watch_projection(2, "Owned DEF", "DEF", 2, 2, 18.0, 50),
        _watch_projection(3, "Owned MID", "MID", 3, 3, 20.0, 65),
        _watch_projection(4, "Owned FWD", "FWD", 4, 4, 21.0, 70),
    ]
    external = [
        _watch_projection(101, "Watch GK", "GK", 1, 5, 19.0, 50),
        _watch_projection(102, "Watch DEF", "DEF", 2, 6, 24.0, 55),
        _watch_projection(103, "Watch MID", "MID", 3, 7, 27.0, 70),
        _watch_projection(104, "Watch FWD", "FWD", 4, 8, 28.0, 75),
    ]
    (tmp_path / "projections.json").write_text(json.dumps({"planning_gw": 2, "players": owned + external}))
    (tmp_path / "team.json").write_text(json.dumps({"team_value_ledger": [{"element": p["element"], "sell_cost": p["now_cost"]} for p in owned]}))
    packages = []
    for p in external:
        packages.append({
            "id": f"1:->{p['element']}",
            "changes": 1,
            "legal": True,
            "ins": [{"element": p["element"], "name": p["name"], "now_cost": p["now_cost"]}],
            "affordability": {"resulting_itb": 0},
            "score": {"valid": True, "robust_score": 105.0},
        })
    (tmp_path / "package_optimizer.json").write_text(json.dumps({"hold": {"score": {"robust_score": 100.0}}, "packages": packages}))
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
    p = _watch_projection(101, "Candidate", "MID", 3, 5, 25.0, 70)
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


def test_sanitize_removes_internal_price_health_code_from_public_row():
    payload = {
        "status": "READY",
        "screening_contract": "FULL_DSS_SCREEN_V1",
        "positions": {
            "MID": [{
                "element": 10,
                "dimensions": {"role": {"status": "PROXY"}},
                "package_context": {"package_id": "1:1->10"},
                "underlying": {"xg90": 0.2, "sources": {"xg90": "position_prior"}},
                "price_risk": {
                    "official_progress_pct": 91.0,
                    "prediction_source": "TRAJECTORY_RATE",
                    "official_projection_health": "SUSPECT_STATIC_OFFSET0",
                },
            }]
        },
    }
    clean = watchlist_public_sanitize.sanitize(payload)
    row = clean["positions"]["MID"][0]
    assert "official_projection_health" not in row["price_risk"]
    assert row["price_risk"]["projection_confidence_note"] == "proyeksi waktu perubahan harga belum cukup yakin"
    assert "dimensions" not in row
    assert "package_context" not in row
    assert "sources" not in row["underlying"]
    assert "SUSPECT_STATIC_OFFSET0" not in json.dumps(clean["positions"], ensure_ascii=False)
    assert clean["candidate_audit"]["10"]["price_risk"]["official_projection_health"] == "SUSPECT_STATIC_OFFSET0"
    assert clean["screening_contract"] == "FULL_DSS_SCREEN_V1"


def test_non_ready_watchlist_cannot_claim_ready_screening_contract():
    payload = {"status": "BLOCKED", "screening_contract": "FULL_DSS_SCREEN_V1", "positions": {"GK": [], "DEF": [], "MID": [], "FWD": []}}
    clean = watchlist_public_sanitize.sanitize(payload)
    assert clean["screening_contract"] == "FULL_DSS_SCREEN_INCOMPLETE_V1"
    assert clean["public_contract"]["ready_contract_requires_ready_status"] is True


def _operational_player(element: int, position: str, team_id: int) -> dict:
    return {
        "element": element,
        "position": position,
        "team_id": team_id,
        "xpts_by_gw": [{"gw": gw, "mean": 4.0 + (element % 3) * 0.1, "std": 1.5} for gw in range(2, 17)],
    }


def _legal_shape_players() -> list[dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return [_operational_player(idx + 1, position, (idx % 7) + 1) for idx, position in enumerate(positions)]


def test_every_operationalization_capability_has_registered_evaluator():
    policy = load_policy()
    capabilities = policy["capabilities"]
    assert capabilities
    for probe, spec in capabilities.items():
        assert spec.get("owner"), probe
        assert spec.get("evaluator") in EVALUATORS, probe
        if "fallback" in spec:
            assert spec["fallback"], probe
    assert policy["policy"]["missing_external_evidence_is_never_fabricated"] is True
    assert policy["policy"]["strict_postflight_requires_all_dss_active"] is True


def test_transfer_momentum_uses_official_counts_and_current_price_linkage(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(operationalization, "DATA", data)
    players = [{"element": element, "now_cost": 50 + element, "transfers_in_event": element * 10, "transfers_out_event": element * 3} for element in range(1, 21)]
    price_cache = {"players": {str(player["element"]): {"now_cost": player["now_cost"], "ownership": 1.0} for player in players}}
    (data / "universe.json").write_text(json.dumps({"players": players}), encoding="utf-8")
    (data / "price_cache.json").write_text(json.dumps(price_cache), encoding="utf-8")
    spec = load_policy()["capabilities"]["transfer_momentum"]
    ok, detail = operationalization._transfer_momentum(spec)
    assert ok is True
    assert detail["evidence_state"] == "AVAILABLE"
    assert detail["transfer_count_coverage_ratio"] == 1.0
    assert detail["price_cache_linkage_ratio"] == 1.0
    assert detail["current_price_match_ratio"] == 1.0
    assert detail["net_transfers_event"] == sum(player["transfers_in_event"] - player["transfers_out_event"] for player in players)
    assert detail["external_threshold_invented"] is False
    assert detail["predicted_price_change_invented"] is False
    assert load_policy()["evidence_maturity"]["evaluator_available_tier"]["transfer_momentum"] == "DERIVED"


def test_transfer_momentum_fails_closed_when_price_linkage_is_incomplete(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(operationalization, "DATA", data)
    players = [{"element": element, "now_cost": 50, "transfers_in_event": 100, "transfers_out_event": 50} for element in range(1, 21)]
    cache = {str(element): {"now_cost": 50} for element in range(1, 19)}
    (data / "universe.json").write_text(json.dumps({"players": players}), encoding="utf-8")
    (data / "price_cache.json").write_text(json.dumps({"players": cache}), encoding="utf-8")
    ok, detail = operationalization._transfer_momentum(load_policy()["capabilities"]["transfer_momentum"])
    assert ok is False
    assert detail["evidence_state"] == "INSUFFICIENT"
    assert detail["price_cache_linkage_ratio"] == 0.9


def test_package_optimizer_executes_cluster_and_early_season_guardrails():
    cfg = load_config()
    players = _legal_shape_players()
    scored = score_package(players, planning_gw=2, changes=0)
    assert scored["valid"] is True
    guards = scored["guardrails"]
    assert guards["team_cluster_penalty_enabled"] is True
    assert guards["early_season_change_cap_enabled"] is True
    assert scored["team_cluster_penalty_points"] >= 0
    early = cfg["early_season_change_cap"]
    over_cap = int(early["max_changes"]) + 1
    rejected = score_package(players, planning_gw=min(2, int(early["through_gw"])), changes=over_cap)
    assert rejected["valid"] is False
    assert rejected["reason"] == "early_season_change_cap_exceeded"
