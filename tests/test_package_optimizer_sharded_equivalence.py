from __future__ import annotations

import json
from pathlib import Path

from src.engines import package_optimizer_exhaustive_accelerated as canonical
from src.runtime_v3 import package_optimizer_shards


def _player(
    element: int,
    position: str,
    team_id: int,
    means: list[float],
    cost: int = 50,
    std: float = 1.0,
) -> dict:
    rows = [{"gw": 3 + index, "mean": float(mean), "std": float(std)} for index, mean in enumerate(means)]
    running = 0.0
    variance = 0.0
    horizons = {}
    for index, mean in enumerate(means, start=1):
        running += float(mean)
        variance += float(std) * float(std)
        if index in (3, 5, 10, 15):
            horizons[str(index)] = {"mean": running, "std": variance**0.5}
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": cost,
        "status": "a",
        "xpts_by_gw": rows,
        "horizons": horizons,
    }


def _owned() -> list[dict]:
    positions = ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)]
    rows = []
    for index, position in enumerate(positions, start=1):
        rows.append(_player(index, position, ((index - 1) % 20) + 1, [3.0] * 15, 50, 1.0))
    return rows


def _team(owned: list[dict]) -> dict:
    return {
        "team_value_ledger": [
            {"element": row["element"], "sell_cost": row["now_cost"]}
            for row in owned
        ],
        "totals": {"itb": 0},
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _top_signature(payload: dict) -> list[tuple[str, float]]:
    return [
        (str(row.get("id")), float((row.get("score") or {}).get("robust_score") or 0.0))
        for row in payload.get("packages") or []
    ]


def _frontier_ids(payload: dict) -> list[str]:
    return [str(row.get("id")) for row in (payload.get("efficient_frontier") or {}).get("packages") or []]


def test_sharded_reducer_is_differentially_equivalent_to_canonical_exhaustive(monkeypatch, tmp_path):
    owned = _owned()
    candidates = [
        _player(100, "GK", 16, [4.1] * 15, 50, 0.9),
        _player(101, "DEF", 17, [4.4] * 15, 50, 0.9),
        _player(102, "MID", 18, [5.2] * 15, 50, 0.8),
        _player(103, "MID", 19, [4.8] * 15, 50, 1.0),
        _player(104, "FWD", 20, [4.7] * 15, 50, 0.9),
    ]
    projections = {"planning_gw": 3, "players": owned + candidates}
    team = _team(owned)
    _write(tmp_path / "projections.json", projections)
    _write(tmp_path / "team.json", team)
    _write(tmp_path / "latest.json", {})

    monkeypatch.setattr(package_optimizer_shards, "DATA", tmp_path)
    monkeypatch.setattr(package_optimizer_shards, "optimizer_input_fingerprint", lambda: "f" * 64)

    plan = package_optimizer_shards.build_plan()
    shard_dir = tmp_path / "shard-results"
    shard_dir.mkdir()
    for shard in plan["shards"]:
        shard_id = int(shard["shard_id"])
        result = package_optimizer_shards.run_shard(plan, shard_id)
        _write(shard_dir / f"shard-{shard_id}.json", result)

    reduced = package_optimizer_shards.reduce_shards(plan, shard_dir, persist=False)
    canonical_result = canonical.build_exhaustive(
        projections,
        team,
        top_keep=int(package_optimizer_shards.load_policy()["planner"]["top_keep_per_shard"]),
    )

    reduced_diag = reduced["search_diagnostics"]
    canonical_diag = canonical_result["search_diagnostics"]
    assert reduced["status"] == canonical_result["status"] == "READY"
    assert reduced_diag["search_authority"] == canonical_diag["search_authority"] == "FULL"
    assert reduced["package_count"] == canonical_result["package_count"]
    for key in (
        "single_candidates_considered",
        "single_step_legal",
        "single_exact_scored",
        "pair_candidate_combinations",
        "pair_step_legal",
        "pair_candidates_exact_scored",
    ):
        assert reduced_diag[key] == canonical_diag[key]
    assert reduced_diag["all_step_legal_packages_scored"] is True
    assert canonical_diag["all_step_legal_packages_scored"] is True
    assert _top_signature(reduced) == _top_signature(canonical_result)
    assert (reduced.get("efficient_frontier") or {}).get("count") == (canonical_result.get("efficient_frontier") or {}).get("count")
    assert _frontier_ids(reduced) == _frontier_ids(canonical_result)

    for result in (reduced, canonical_result):
        governance = result.get("governance") or {}
        assert governance.get("candidate_generation_only") is True
        assert governance.get("final_go_requires_framework_governance_and_postflight_gate0") is True
        frontier = result.get("efficient_frontier") or {}
        assert frontier.get("dimensions_pending_richer_runtime_evidence") == []
        assert "xmins_uncertainty_minutes_std_sum" in (frontier.get("dimensions_used") or [])
        assert "tactical_role_uncertainty_missing_dimensions" in (frontier.get("dimensions_used") or [])
        assert "price_risk_adverse_progress_percent" in (frontier.get("dimensions_used") or [])
        assert "club_slot_headroom" in (frontier.get("dimensions_used") or [])
        assert "roster_change_uncertainty_players" in (frontier.get("dimensions_used") or [])
