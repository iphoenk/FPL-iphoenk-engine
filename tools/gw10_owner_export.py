from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
FORMATIONS = ("5-3-2", "5-2-3", "5-4-1", "4-4-2", "4-3-3", "4-5-1", "3-5-2", "3-4-3")
OFFICIAL_METRICS = (
    "minutes", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "saves", "goals_prevented", "defensive_contribution",
    "bonus", "bps", "expected_goals", "expected_assists",
    "expected_goal_involvements", "expected_goals_conceded", "penalties_saved",
    "penalties_missed", "yellow_cards", "red_cards", "own_goals",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def official_payload(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = snapshot.get("data") or {}
    bootstrap_node = data.get("bootstrap") or {}
    fixtures_node = data.get("fixtures") or {}
    bootstrap = bootstrap_node.get("json") if isinstance(bootstrap_node, dict) else None
    fixtures = fixtures_node.get("json") if isinstance(fixtures_node, dict) else None
    if not isinstance(bootstrap, dict):
        bootstrap = snapshot.get("official") or {}
    if not isinstance(fixtures, list):
        fixtures = (snapshot.get("official") or {}).get("fixtures") or []
    return bootstrap, [row for row in fixtures if isinstance(row, dict)]


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for metric in OFFICIAL_METRICS:
        values = [number(row.get(metric)) for row in rows]
        out[metric] = sum(values) if values and all(value is not None for value in values) else None
    return out


def build(args: argparse.Namespace) -> dict[str, Any]:
    runtime = args.runtime_root / "data/v6"
    history_path = runtime / "history/official_detail.json.gz"
    sidecar_path = runtime / "history/official_detail.json"
    snapshot_path = runtime / "current/official_fpl.json"
    team_path = args.private_root / "personal/current_team.json"
    with gzip.open(history_path, "rt", encoding="utf-8") as handle:
        detail = json.load(handle)
    full = detail["full_season_history"]
    sidecar = read_json(sidecar_path)
    archive_run_id = detail.get("report_prefetch_run_id")
    archive_slot = aware(detail.get("target_logical_report_slot"))
    sidecar_slot = aware(sidecar.get("target_logical_report_slot"))
    archive_generated = aware(detail.get("generated_at"))
    sidecar_generated = aware(sidecar.get("generated_at"))
    archive_binding_pass = (
        isinstance(archive_run_id, str) and bool(archive_run_id.strip())
        and archive_run_id == sidecar.get("report_prefetch_run_id")
        and archive_slot is not None and archive_slot == sidecar_slot
        and archive_generated is not None and archive_generated == sidecar_generated
    )
    if not archive_binding_pass:
        raise ValueError("full history archive is not bound to the sidecar occurrence")
    snapshot = read_json(snapshot_path)
    current = read_json(team_path)
    bootstrap, fixtures = official_payload(snapshot)
    elements = {int(row["id"]): row for row in bootstrap.get("elements") or [] if row.get("id") is not None}
    teams = {int(row["id"]): row for row in bootstrap.get("teams") or [] if row.get("id") is not None}
    owned = [int(row["element_id"]) for row in current.get("players") or []]
    if len(owned) != 15 or len(set(owned)) != 15:
        raise ValueError("current_team must contain 15 unique element IDs")
    history_players = full.get("players") or {}
    rows: list[dict[str, Any]] = []
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for element_id in owned:
        element = elements[element_id]
        player = history_players[str(element_id)]
        for gw in (7, 8, 9):
            record = (player.get("history") or {}).get(str(gw))
            if not isinstance(record, dict):
                raise ValueError(f"missing actual history for element={element_id} gw={gw}")
            fixture_rows = [dict(row) for row in record.get("fixtures") or [] if isinstance(row, dict)]
            agg = aggregate(fixture_rows)
            opponent_ids = sorted({int(row["opponent_team"]) for row in fixture_rows if row.get("opponent_team") is not None})
            home_flags = {bool(row.get("was_home")) for row in fixture_rows}
            row = {
                "element_id": element_id,
                "player": element.get("web_name"),
                "team_id": int(element.get("team") or 0),
                "team": (teams.get(int(element.get("team") or 0)) or {}).get("short_name"),
                "position": POSITIONS.get(int(element.get("element_type") or 0), "UNKNOWN"),
                "gw": gw,
                "opponent_ids": ",".join(str(value) for value in opponent_ids),
                "venue": "HOME" if home_flags == {True} else "AWAY" if home_flags == {False} else "MULTI_OR_BLANK",
                "status": record.get("status"),
                "fixture_count": len(fixture_rows),
                **agg,
                "source_class": "OFFICIAL",
                "source": "Official FPL element-summary/{element_id}/",
                "source_generated_at": detail.get("generated_at"),
                "report_prefetch_run_id": detail.get("report_prefetch_run_id"),
            }
            rows.append(row)
            by_player[element_id].append(row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "gw10_our15_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    player_l3 = []
    for element_id in owned:
        l3 = by_player[element_id]
        minutes_values = [number(row.get("minutes")) for row in l3]
        minutes = sum(minutes_values) if all(value is not None for value in minutes_values) else None
        metric_totals = {}
        for metric in OFFICIAL_METRICS:
            values = [number(row.get(metric)) for row in l3]
            metric_totals[metric] = sum(values) if all(value is not None for value in values) else None
        per90 = {
            metric: round(value * 90 / minutes, 4) if value is not None and minutes is not None and minutes > 0 else None
            for metric, value in metric_totals.items() if metric != "minutes"
        }
        points = [number(row.get("total_points")) for row in l3]
        complete_points = all(value is not None for value in points)
        mean = sum(points) / len(points) if complete_points else None
        variance = sum((value - mean) ** 2 for value in points) / len(points) if complete_points else None
        weights = (0.2, 0.3, 0.5)
        player_l3.append({
            "element_id": element_id,
            "player": elements[element_id].get("web_name"),
            "position": POSITIONS[int(elements[element_id]["element_type"])],
            "raw_l3": metric_totals,
            "per90_l3": per90,
            "weighted_recency_points": round(sum(value * weight for value, weight in zip(points, weights)), 4) if complete_points else None,
            "trend_points_gw7_to_gw9": points,
            "points_variance": round(variance, 4) if variance is not None else None,
            "minutes_security_l3": round(sum(1 for value in minutes_values if value is not None and value >= 60) / 3, 4) if all(value is not None for value in minutes_values) else None,
        })
    position_payload = {
        "contract": "GW10_POSITION_METRICS_V1",
        "planning_gw": 10,
        "actual_horizon": [7, 8, 9],
        "generated_from": {"history_sha256": sha256(history_path), "current_team_sha256": sha256(team_path)},
        "metric_provenance": {
            metric: {"class": "OFFICIAL", "scope": "MATCH_LEVEL_ACTUAL"} for metric in OFFICIAL_METRICS
        },
        "unavailable": {
            "psxg_minus_ga": "UNAVAILABLE",
            "heatmap": "UNAVAILABLE",
            "average_position": "UNAVAILABLE",
            "pressing": "UNAVAILABLE",
        },
        "players": player_l3,
    }
    (args.output_dir / "gw10_position_metrics.json").write_text(json.dumps(position_payload, indent=2, sort_keys=True) + "\n")

    owned_teams = sorted({int(elements[element_id]["team"]) for element_id in owned})
    future = []
    for fixture in fixtures:
        gw = fixture.get("event")
        if not isinstance(gw, int) or not 10 <= gw <= 14:
            continue
        for team_id, opponent_id, home in (
            (fixture.get("team_h"), fixture.get("team_a"), True),
            (fixture.get("team_a"), fixture.get("team_h"), False),
        ):
            if team_id in owned_teams:
                future.append({
                    "gw": gw, "fixture_id": fixture.get("id"), "team_id": team_id,
                    "team": (teams.get(team_id) or {}).get("short_name"),
                    "opponent_id": opponent_id, "opponent": (teams.get(opponent_id) or {}).get("short_name"),
                    "home": home, "kickoff_time": fixture.get("kickoff_time"),
                    "finished": fixture.get("finished"), "source_class": "OFFICIAL",
                })
    opponent_payload = {
        "contract": "GW10_OPPONENT_INTELLIGENCE_V1",
        "planning_horizon": [10, 11, 12, 13, 14],
        "official_fixtures": sorted(future, key=lambda row: (row["gw"], row["team_id"], row["fixture_id"])),
        "verified_interpretation_boundary": {
            "schedule_and_club_affiliation": "OFFICIAL",
            "tactical_formation_pressing_transition_line": "UNAVAILABLE",
            "clean_sheet_probability": "MODEL_RECOMPUTATION_BLOCKED",
            "xgc_and_big_chances_conceded_l3": "THIRD_PARTY_MATCH_LEVEL_NOT_AVAILABLE_IN_BOUND_OCCURRENCE",
        },
    }
    (args.output_dir / "gw10_opponent_intelligence.json").write_text(json.dumps(opponent_payload, indent=2, sort_keys=True) + "\n")

    squad_rows = {int(row["element_id"]): row for row in current.get("players") or []}
    gvardiol = squad_rows.get(391)
    transfer_routes = []
    for incoming_id, label in ((566, "Gvardiol to Silva"), (229, "Gvardiol to Tarkowski")):
        incoming = elements.get(incoming_id)
        sell_price = (gvardiol or {}).get("selling_price")
        buy_price = (incoming or {}).get("now_cost")
        bank = current.get("bank")
        remaining = None if None in (sell_price, buy_price, bank) else int(bank) + int(sell_price) - int(buy_price)
        transfer_routes.append({
            "route": label, "out_element_id": 391, "in_element_id": incoming_id,
            "sell_price": sell_price, "buy_price": buy_price, "bank_remaining": remaining,
            "budget_legal": remaining is not None and remaining >= 0,
            "already_owned": incoming_id in owned,
            "utility_1gw": None, "utility_3gw": None, "utility_5gw": None,
            "recommendation_state": "BLOCKED_V12_RECOMPUTATION_NOT_TERMINAL",
        })
    transfer_payload = {
        "contract": "GW10_TRANSFER_FRONTIER_V1",
        "current_finance": {"bank": current.get("bank"), "free_transfers": current.get("free_transfers"), "authority": current.get("authority")},
        "hold": {"route": "HOLD", "utility_1gw": None, "utility_3gw": None, "utility_5gw": None},
        "routes": transfer_routes,
        "best_universe_defender": None,
        "palmer_midfielder_frontier": None,
        "status": "BLOCKED",
        "reason": "V12 exact occurrence publication gate did not become terminal; utility and recommendation were not fabricated",
    }
    (args.output_dir / "gw10_transfer_frontier.json").write_text(json.dumps(transfer_payload, indent=2, sort_keys=True) + "\n")
    formation_payload = {
        "contract": "GW10_FORMATION_COMPARISON_V1",
        "formations": [{"formation": value, "xpts": None, "status": "BLOCKED"} for value in FORMATIONS],
        "sensitivity_3_5_2_vs_5_3_2": None,
        "captain_vice_frontier": None,
        "bench_optimization": None,
        "mc": {"status": "BLOCKED", "actual_paths": 0, "reason": transfer_payload["reason"]},
    }
    (args.output_dir / "gw10_formation_comparison.json").write_text(json.dumps(formation_payload, indent=2, sort_keys=True) + "\n")
    partition_evidence = {}
    for gw in (7, 8, 9):
        partition = read_json(runtime / f"history/official_gw_{gw}.json")
        partition_evidence[str(gw)] = {
            "status": (partition.get("coverage") or {}).get("status"),
            "players": len(partition.get("players") or {}),
            "source_run_match": bool(archive_run_id) and partition.get("report_prefetch_run_id") == archive_run_id,
            "logical_slot_match": archive_slot is not None and aware(partition.get("target_logical_report_slot")) == archive_slot,
        }
    expected_players = int((full.get("universe") or {}).get("expected_players") or 0)
    actual_ids = (full.get("universe") or {}).get("element_ids") or []
    partition_pass = all(
        evidence["status"] == "PASS"
        and evidence["players"] == expected_players
        and evidence["source_run_match"]
        and evidence["logical_slot_match"]
        for evidence in partition_evidence.values()
    )
    history_pass = (
        (full.get("coverage_gate") or {}).get("status") == "PASS"
        and expected_players > 0
        and len(actual_ids) == expected_players
        and len(set(actual_ids)) == expected_players
    )
    current_at = aware(current.get("generated_at"))
    history_at = aware(detail.get("generated_at"))
    current_team_pass = (
        str(current.get("auth_state") or "").upper() in {"AVAILABLE", "AUTH_AVAILABLE"}
        and current.get("entry_id") == 3462711
        and current.get("editable_planning_gw") == 10
        and isinstance(current.get("bank"), int)
        and isinstance(current.get("free_transfers"), int)
        and current_at is not None
        and history_at is not None
        and current_at <= history_at
        and (history_at - current_at).total_seconds() <= 6 * 60 * 60
    )
    actual_slot_keys = {(row["element_id"], row["gw"]) for row in rows}
    our15_pass = (
        len(rows) == 45
        and len(actual_slot_keys) == 45
        and all(row["status"] in {"FINAL", "DNP", "BLANK"} for row in rows)
    )
    acceptance = {
        "contract": "GW10_ACCEPTANCE_V1",
        "occurrence": sidecar.get("target_logical_report_slot"),
        "source_run_id": sidecar.get("report_prefetch_run_id"),
        "gates": {
            "official_gw7_9_exports": {"status": "PASS" if partition_pass else "FAIL", "partitions": partition_evidence},
            "universe_completeness": {"status": "PASS" if history_pass else "FAIL", "expected": expected_players, "actual": len(actual_ids)},
            "fixture_identity": {"status": full["coverage_gate"]["fixture_identity_status"]},
            "metric_missingness": {"status": full["coverage_gate"]["metric_identity_status"]},
            "our15_45_actual_slots": {"status": "PASS" if our15_pass else "FAIL", "actual": len(rows)},
            "current_team_finance": {"status": "PASS" if current_team_pass else "FAIL", "generated_at": current.get("generated_at")},
            "v12_full_recomputation": {"status": "BLOCKED", "reason": transfer_payload["reason"]},
            "formation_mc500k": {"status": "BLOCKED", "actual_paths": 0},
            "recommendation": {"status": "BLOCKED", "reason": "No truthful full-V12 score frontier available"},
        },
    }
    (args.output_dir / "gw10_acceptance.json").write_text(json.dumps(acceptance, indent=2, sort_keys=True) + "\n")
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
