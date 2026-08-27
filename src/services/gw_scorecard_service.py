from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from src.services.contracts import file_digest
from src.utils import DATA, atomic_json, iso_now, read_json

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"
LINEUP = DATA / "lineup_decision_v4.json"
OUTFILE = DATA / "gw_scorecard_v4.json"
ARCHIVE_DIR = DATA / "gw_results"

POSITION_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_NAMES = {
    "bboost": "BENCH_BOOST",
    "bench_boost": "BENCH_BOOST",
    "3xc": "TRIPLE_CAPTAIN",
    "triple_captain": "TRIPLE_CAPTAIN",
    "wildcard": "WILDCARD",
    "freehit": "FREE_HIT",
    "free_hit": "FREE_HIT",
}
CHIP_SHORT = {
    "BENCH_BOOST": "BB",
    "TRIPLE_CAPTAIN": "TC",
    "WILDCARD": "WC",
    "FREE_HIT": "FH",
    "NONE": "NONE",
}


def _normalize_chip(value: str | None) -> str:
    if not value:
        return "NONE"
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return CHIP_NAMES.get(key, str(value).strip().upper().replace(" ", "_"))


def _event_chip(history: dict, gw: int) -> str:
    for row in history.get("chips", []) or []:
        if int(row.get("event") or 0) == int(gw):
            return _normalize_chip(row.get("name"))
    return "NONE"


def _event_finished(bootstrap: dict, gw: int) -> bool:
    event = next((row for row in bootstrap.get("events", []) if int(row.get("id") or 0) == int(gw)), None)
    return bool(event and event.get("finished"))


def _official_history_row(history: dict, gw: int) -> dict:
    return next((row for row in history.get("current", []) or [] if int(row.get("event") or 0) == int(gw)), {})


def build_actual_gw(raw: dict, gw: int) -> dict | None:
    """Build a finished-GW result only from the already-acquired raw snapshot."""
    phase = raw.get("phase") or {}
    official = raw.get("official") or {}
    if int(phase.get("submitted_gw") or 0) != int(gw) or int(phase.get("scoring_gw") or 0) != int(gw):
        return None
    bootstrap = official.get("bootstrap") or {}
    if not _event_finished(bootstrap, gw):
        return None
    picks = official.get("picks") or {}
    event_live = official.get("event_live") or {}
    if not picks.get("picks") or not event_live.get("elements"):
        return None

    by_id = {int(row["id"]): row for row in bootstrap.get("elements", [])}
    teams = {int(row["id"]): row.get("name") for row in bootstrap.get("teams", [])}
    live_by_id = {int(row["id"]): row for row in event_live.get("elements", [])}
    players: list[dict] = []
    gross_points = 0
    bench_raw_points = 0
    bench_counted_points = 0

    for pick in picks.get("picks", []):
        element = int(pick.get("element") or 0)
        player = by_id.get(element) or {}
        stats = (live_by_id.get(element) or {}).get("stats") or {}
        raw_points = int(stats.get("total_points") or 0)
        multiplier = max(0, int(pick.get("multiplier") or 0))
        counted = raw_points * multiplier
        pick_position = int(pick.get("position") or 0)
        gross_points += counted
        if pick_position > 11:
            bench_raw_points += raw_points
            bench_counted_points += counted
        players.append({
            "element": element,
            "name": player.get("web_name"),
            "team": teams.get(int(player.get("team") or 0)),
            "position": POSITION_BY_TYPE.get(player.get("element_type")),
            "pick_position": pick_position,
            "bench": pick_position > 11,
            "multiplier": multiplier,
            "captain": bool(pick.get("is_captain")),
            "vice_captain": bool(pick.get("is_vice_captain")),
            "raw_points": raw_points,
            "counted_points": counted,
            "minutes": int(stats.get("minutes") or 0),
        })

    entry_history = picks.get("entry_history") or {}
    hit = int(entry_history.get("event_transfers_cost") or 0)
    net_points = gross_points - hit
    history = official.get("history") or {}
    official_row = _official_history_row(history, gw)
    official_points = official_row.get("points")
    if official_points is None:
        official_points = entry_history.get("points")
    official_points = int(official_points) if official_points is not None else None
    chip = _event_chip(history, gw)
    captain = next((row for row in players if row.get("captain")), None)
    vice = next((row for row in players if row.get("vice_captain")), None)

    return {
        "schema_version": 494,
        "engine": "v4.9.4-personal-gw-result",
        "status": "FINAL",
        "gw": int(gw),
        "captured_at": iso_now(),
        "team_id": raw.get("team_id"),
        "chip": chip,
        "chip_short": CHIP_SHORT.get(chip, chip),
        "gross_points": gross_points,
        "hit": hit,
        "net_points": net_points,
        "official_points": official_points,
        "official_points_match": official_points is None or official_points == net_points,
        "bench_raw_points": bench_raw_points,
        "bench_counted_points": bench_counted_points,
        "captain": captain,
        "vice_captain": vice,
        "players": players,
        "official_history": {
            "overall_rank": official_row.get("overall_rank", entry_history.get("overall_rank")),
            "event_rank": official_row.get("rank", entry_history.get("rank")),
            "points_on_bench": official_row.get("points_on_bench", entry_history.get("points_on_bench")),
            "team_value": official_row.get("value", entry_history.get("value")),
            "bank": official_row.get("bank", entry_history.get("bank")),
        },
        "source": "raw_snapshot.official.picks_plus_event_live_plus_history",
        "guardrails": {
            "official_api_refetch": False,
            "finished_event_required": True,
            "multiplier_aware": True,
            "hit_deducted_from_gross": True,
        },
    }


def _bench_rows(lineup: dict) -> list[dict]:
    bench = lineup.get("bench") or {}
    rows: list[dict] = []
    if bench.get("gk"):
        rows.append(dict(bench["gk"], slot="GK"))
    for row in bench.get("order", []) or []:
        rows.append(dict(row, slot=row.get("slot")))
    return rows


def build_planning_projection(lineup: dict, planning_gw: int | None) -> dict:
    if not planning_gw:
        return {"status": "NONE", "gw": None, "reason": "no_planning_gw"}
    starting = list(lineup.get("starting_xi") or [])
    if len(starting) != 11 or not lineup.get("captain") or not lineup.get("vice_captain"):
        return {"status": "UNAVAILABLE", "gw": int(planning_gw), "reason": "lineup_contract_incomplete"}

    xi_sum = round(sum(float(row.get("xpts") or 0.0) for row in starting), 3)
    published_xi = round(float(lineup.get("xi_xpts") or 0.0), 3)
    if abs(xi_sum - published_xi) > 0.05:
        raise RuntimeError(f"lineup xPts mismatch: sum={xi_sum} published={published_xi}")

    captain = dict(lineup["captain"])
    vice = dict(lineup["vice_captain"])
    captain_xpts = float(captain.get("xpts") or 0.0)
    active_chip = _normalize_chip((lineup.get("chip_context") or {}).get("active_chip"))
    captain_multiplier = 3 if active_chip == "TRIPLE_CAPTAIN" else 2
    captain_extra = captain_xpts * (captain_multiplier - 1)
    bench_rows = _bench_rows(lineup)
    bench_xpts = round(sum(float(row.get("xpts") or 0.0) for row in bench_rows), 3)
    bench_counted = bench_xpts if active_chip == "BENCH_BOOST" else 0.0
    standard_points = round(xi_sum + captain_xpts, 2)
    expected_points = round(xi_sum + captain_extra + bench_counted, 2)

    return {
        "status": "PROJECTION",
        "gw": int(planning_gw),
        "formation": lineup.get("formation"),
        "xi_xpts": round(xi_sum, 2),
        "captain": {"element": captain.get("element"), "name": captain.get("name"), "xpts": round(captain_xpts, 3), "multiplier": captain_multiplier},
        "vice_captain": {"element": vice.get("element"), "name": vice.get("name"), "xpts": round(float(vice.get("xpts") or 0.0), 3)},
        "active_chip": active_chip,
        "chip_short": CHIP_SHORT.get(active_chip, active_chip),
        "bench_xpts": round(bench_xpts, 2),
        "bench_counted_xpts": round(bench_counted, 2),
        "standard_captain_team_xpts": standard_points,
        "estimated_points": expected_points,
        "starting_xi": [{"element": row.get("element"), "name": row.get("name"), "position": row.get("position"), "xpts": row.get("xpts")} for row in starting],
        "bench": [{"slot": row.get("slot"), "element": row.get("element"), "name": row.get("name"), "position": row.get("position"), "xpts": row.get("xpts")} for row in bench_rows],
        "uncertainty": {
            "status": "DEFERRED",
            "reason": "team_level_correlated_score_distribution_not_yet_calibrated",
            "player_intervals_not_naively_summed": True,
        },
        "guardrails": {
            "projection_from_lineup_contract": True,
            "captain_multiplier_applied_once": True,
            "bench_only_counted_for_bench_boost": True,
            "no_extra_official_api_fetch": True,
        },
    }


def _archive_path(directory: Path, gw: int) -> Path:
    return directory / f"gw{int(gw):02d}.json"


def archive_finished_gw(actual: dict, directory: Path = ARCHIVE_DIR, simulated: bool = False) -> tuple[dict, str, bool]:
    gw = int(actual["gw"])
    path = _archive_path(directory, gw)
    if path.exists():
        existing = read_json(path, {})
        if int(existing.get("gw") or 0) != gw or existing.get("status") != "FINAL":
            raise RuntimeError(f"invalid existing GW archive: {path}")
        comparable = ("gross_points", "hit", "net_points", "chip")
        consistent = all(existing.get(key) == actual.get(key) for key in comparable)
        return existing, "PRESERVED", consistent
    if simulated:
        return actual, "SIMULATION_NOT_WRITTEN", True
    atomic_json(path, actual)
    return actual, "CREATED", True


def _archive_history(directory: Path = ARCHIVE_DIR) -> list[dict]:
    out: list[dict] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("gw*.json")):
        row = read_json(path, {})
        if row.get("status") != "FINAL" or not row.get("gw"):
            continue
        out.append({
            "gw": row.get("gw"),
            "points": row.get("net_points"),
            "gross_points": row.get("gross_points"),
            "hit": row.get("hit"),
            "chip": row.get("chip"),
            "chip_short": row.get("chip_short"),
            "captain": (row.get("captain") or {}).get("name"),
        })
    return out


def _headline_previous(previous: dict) -> str | None:
    if previous.get("status") != "FINAL":
        return None
    chip = previous.get("chip_short") or "NONE"
    suffix = f" · {chip}" if chip != "NONE" else ""
    return f"GW{previous['gw']} FINAL · {previous['net_points']} pts{suffix}"


def _headline_projection(projection: dict) -> str | None:
    if projection.get("status") != "PROJECTION":
        return None
    chip = projection.get("chip_short") or "NONE"
    chip_text = f" · {chip}" if chip != "NONE" else ""
    captain = (projection.get("captain") or {}).get("name")
    return f"GW{projection['gw']} PROJECTION · {projection['estimated_points']:.1f} xPts{chip_text} · {projection.get('formation')} · C {captain}"


def run() -> dict:
    started = perf_counter()
    raw = read_json(SNAPSHOT, {})
    lineup = read_json(LINEUP, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("snapshot.v1 required")
    if not lineup:
        raise RuntimeError("lineup decision required")

    phase = raw.get("phase") or {}
    last_finished = phase.get("last_finished_gw")
    planning_gw = phase.get("planning_gw")
    simulated = raw.get("as_of") is not None or (raw.get("checkpoint_context") or {}).get("is_simulation") is True
    archive_action = "NO_FINISHED_GW"
    archive_consistent = True
    previous: dict = {"status": "NONE", "gw": last_finished, "reason": "no_finished_gw"}

    if last_finished:
        archive_file = _archive_path(ARCHIVE_DIR, int(last_finished))
        existing = read_json(archive_file, {}) if archive_file.exists() else {}
        actual = build_actual_gw(raw, int(last_finished))
        if actual:
            previous, archive_action, archive_consistent = archive_finished_gw(actual, ARCHIVE_DIR, simulated=simulated)
        elif existing:
            previous = existing
            archive_action = "PRESERVED"
        else:
            previous = {"status": "UNAVAILABLE", "gw": int(last_finished), "reason": "finished_gw_source_not_in_current_snapshot_and_archive_missing"}
            archive_action = "MISSING_SOURCE"

    projection = build_planning_projection(lineup, int(planning_gw) if planning_gw else None)
    history = _archive_history(ARCHIVE_DIR)
    if previous.get("status") == "FINAL" and not any(int(row.get("gw") or 0) == int(previous.get("gw") or 0) for row in history):
        history.append({
            "gw": previous.get("gw"), "points": previous.get("net_points"), "gross_points": previous.get("gross_points"),
            "hit": previous.get("hit"), "chip": previous.get("chip"), "chip_short": previous.get("chip_short"),
            "captain": (previous.get("captain") or {}).get("name"),
        })
        history.sort(key=lambda row: int(row.get("gw") or 0))

    out = {
        "schema_version": 494,
        "engine": "v4.9.4-personal-gw-scorecard",
        "generated_at": iso_now(),
        "status": "PASS",
        "team_id": raw.get("team_id"),
        "phase": phase,
        "snapshot_sha256": file_digest(SNAPSHOT),
        "previous_gw": previous,
        "planning_gw": projection,
        "history": history,
        "headline": {
            "previous": _headline_previous(previous),
            "planning": _headline_projection(projection),
        },
        "archive": {
            "action": archive_action,
            "consistent_with_current_source": archive_consistent,
            "directory": "data/gw_results",
            "immutable": True,
        },
        "guardrails": {
            "raw_snapshot_only": True,
            "official_api_refetch": False,
            "process_isolated_microservice": True,
            "finished_gw_archive_immutable": True,
            "simulation_never_mutates_archive": True,
            "projection_from_lineup_contract": True,
            "projection_is_estimate_not_actual": True,
            "player_intervals_not_naively_summed": True,
        },
        "performance_ms": round((perf_counter() - started) * 1000, 2),
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "personal_gw_scorecard",
        "status": out["status"],
        "previous": out["headline"]["previous"],
        "planning": out["headline"]["planning"],
        "archive_action": archive_action,
        "duration_ms": out["performance_ms"],
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
