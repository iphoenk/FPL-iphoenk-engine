from __future__ import annotations

"""Thin V12-native integrated report runner.

This module closes the occurrence-execution gap between the V6 factual plane,
the existing V12 P1.x model owners, and the Canonical report renderer.

It is deliberately NOT:
- a scheduler;
- a V6 publisher/acquisition owner;
- a replacement methodology authority;
- a legacy V3/V4/V5 bridge;
- a second optimizer or second report schema.

Canonical V12 remains authority. V6 remains factual plane. Owner modules keep
their mathematics. The runner only binds one report occurrence, executes the
owners whose inputs are supportable, records stage truth, and materializes one
coherent report bundle.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_mini_league_overlay import build_mini_league_snapshot
from src.engines.v12_report_orchestration import (
    build_actionable_price_radar,
    build_price20,
    build_watchlist20,
    materialize_all15,
    materialize_deep_report,
    render_deep_text,
)
from src.engines.v12_tactical_role import attach_tactical_role_scores
from src.models.historical_projection import build as build_player_projections
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.team_strength import build_team_strength

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"
STATE_PATH = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_STATE_V12.json"

SUPPORTED_MODES = {"DEEP"}
LEGACY_RUNTIME_TOKENS = (
    "runtime_v3",
    "runtime_v4",
    "runtime_v5",
    "full_authority_cache",
    "legacy optimizer",
)


class IntegratedRunnerError(RuntimeError):
    pass


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stage(
    ledger: list[dict[str, Any]],
    name: str,
    fn: Callable[[], Any],
    *,
    required: bool = False,
) -> Any:
    try:
        value = fn()
    except Exception as exc:  # occurrence truth must survive one stage failure
        ledger.append(
            {
                "stage": name,
                "status": "FAILED",
                "required": bool(required),
                "error_class": type(exc).__name__,
                "error": str(exc),
            }
        )
        return None
    ledger.append(
        {
            "stage": name,
            "status": "PASS",
            "required": bool(required),
            "output_fingerprint": _fingerprint(value),
        }
    )
    return value


def _require_report_prefetch(
    runtime_root: Path,
    *,
    report_slot: str,
) -> dict[str, Any]:
    proof = _read_json(
        runtime_root / "data/v6/health/report_prefetch.json",
        {},
    ) or {}
    if proof.get("fresh_for_target_report") is not True:
        raise IntegratedRunnerError(
            "same-occurrence report-prefetch is not fresh_for_target_report"
        )
    generated = str(proof.get("generated_at") or "")
    if not generated:
        raise IntegratedRunnerError("report-prefetch generated_at unavailable")
    try:
        generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        slot_dt = datetime.fromisoformat(str(report_slot).replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegratedRunnerError("invalid report-prefetch/report-slot timestamp") from exc
    if generated_dt.tzinfo is None or slot_dt.tzinfo is None:
        raise IntegratedRunnerError("report-prefetch/report-slot timestamps must be timezone-aware")
    age_minutes = abs((slot_dt - generated_dt.astimezone(slot_dt.tzinfo)).total_seconds()) / 60.0
    # Prefetch may finish immediately before or shortly after an HH:30 occurrence.
    if age_minutes > 15.0:
        raise IntegratedRunnerError(
            f"report-prefetch is not same-occurrence current: age_minutes={age_minutes:.2f}"
        )
    return {
        **proof,
        "same_occurrence_bound": True,
        "report_slot": report_slot,
        "age_minutes": round(age_minutes, 3),
    }


def _official_payload(runtime_root: Path) -> dict[str, Any]:
    payload = _read_json(runtime_root / "data/v6/current/official_fpl.json", {}) or {}
    official = payload.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    fixtures = official.get("fixtures") or []
    if not isinstance(bootstrap, Mapping) or not bootstrap.get("elements"):
        raise IntegratedRunnerError("Official FPL bootstrap is unavailable")
    if not isinstance(fixtures, list) or not fixtures:
        raise IntegratedRunnerError("Official FPL fixtures are unavailable")
    return {
        "payload": payload,
        "bootstrap": dict(bootstrap),
        "fixtures": [dict(row) for row in fixtures if isinstance(row, Mapping)],
    }


def _planning_gw(bootstrap: Mapping[str, Any]) -> int:
    events = [dict(row) for row in bootstrap.get("events") or [] if isinstance(row, Mapping)]
    next_rows = [row for row in events if row.get("is_next") is True]
    if next_rows:
        return int(next_rows[0]["id"])
    current = [row for row in events if row.get("is_current") is True]
    if current:
        return int(current[0]["id"]) + 1
    unfinished = [int(row.get("id") or 0) for row in events if not row.get("finished")]
    unfinished = [gw for gw in unfinished if gw > 0]
    return min(unfinished) if unfinished else 1


def _position_name(value: Any) -> str:
    token = str(value or "").upper()
    return "GK" if token in {"GKP", "GK"} else token


def _owned15(
    runtime_root: Path,
    state: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current = _read_json(runtime_root / "data/v6/personal/current_team.json", {}) or {}
    player_map = {
        int(row.get("id")): dict(row)
        for row in bootstrap.get("elements") or []
        if row.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for row in current.get("players") or []:
        if not isinstance(row, Mapping) or row.get("element_id") is None:
            continue
        element = int(row["element_id"])
        official = player_map.get(element) or {}
        rows.append(
            {
                "element_id": element,
                "element": element,
                "name": official.get("web_name") or str(element),
                "position": _position_name(row.get("position")),
                "team_id": int(official.get("team") or 0),
                "now_cost": int(row.get("current_price") or official.get("now_cost") or 0),
                "sell_value": row.get("selling_price"),
                "status": official.get("status"),
                "eligible": True,
                "squad_position": row.get("squad_position"),
                "bench_order": row.get("bench_order"),
                "captain": bool(row.get("captain")),
                "vice_captain": bool(row.get("vice_captain")),
            }
        )
    if len(rows) == 15:
        return rows

    confirmed = (state.get("confirmed_current_squad_state") or {})
    rows = []
    groups = (
        ("goalkeepers", "GK"),
        ("defenders", "DEF"),
        ("midfielders", "MID"),
        ("forwards", "FWD"),
    )
    for group, position in groups:
        for row in confirmed.get(group) or []:
            if row.get("element_id") is None:
                continue
            element = int(row["element_id"])
            official = player_map.get(element) or {}
            rows.append(
                {
                    "element_id": element,
                    "element": element,
                    "name": official.get("web_name") or row.get("display_name") or str(element),
                    "position": position,
                    "team_id": int(official.get("team") or 0),
                    "now_cost": int(official.get("now_cost") or 0),
                    "sell_value": None,
                    "status": official.get("status"),
                    "eligible": True,
                }
            )
    if len(rows) != 15:
        raise IntegratedRunnerError(f"OUR15 identity incomplete: {len(rows)}/15")
    return rows


def _projection_model_rows(
    projections: Mapping[str, Any],
    owned_ids: set[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        element = int(player.get("element") or 0)
        if element not in owned_ids:
            continue
        xmins = dict(player.get("xmins") or {})
        horizons = dict(player.get("horizons") or {})
        tactical = dict(player.get("tactical_role_component") or {})
        gw1 = dict(horizons.get("1") or {})
        gw3 = dict(horizons.get("3") or {})
        gw5 = dict(horizons.get("5") or {})
        rows.append(
            {
                "element_id": element,
                "name": player.get("name"),
                "opponent": (
                    ((player.get("xpts_by_gw") or [{}])[0].get("fixtures") or [{}])[0].get("opponent")
                    if player.get("xpts_by_gw")
                    else "UNAVAILABLE"
                ),
                "recommended_or_locked_role": "UNLOCKED",
                "p_available": xmins.get("availability", xmins.get("overall_availability", "UNAVAILABLE")),
                "p_start": xmins.get("start_probability", "UNAVAILABLE"),
                "p_cameo": xmins.get("cameo_probability", "UNAVAILABLE"),
                "p_dnp": xmins.get("dnp_probability", "UNAVAILABLE"),
                "xmins": xmins.get("expected_minutes", "UNAVAILABLE"),
                "tactical_role": tactical.get("canonical_tactical_role_score", "UNAVAILABLE"),
                "set_piece_penalty_role": {
                    "set_piece": player.get("set_piece_role"),
                    "penalty": player.get("penalty_role"),
                },
                "matchup": tactical.get("fixture_contexts", "UNAVAILABLE"),
                "gw_plus_1": gw1.get("mean", "UNAVAILABLE"),
                "three_gw": gw3.get("mean", "UNAVAILABLE"),
                "five_gw": gw5.get("mean", "UNAVAILABLE"),
                "uncertainty_floor_upside": {
                    "gw1_std": gw1.get("std"),
                    "gw1_distribution": gw1.get("point_distribution"),
                },
                "action": "HOLD",
            }
        )
    return rows


def _candidate_universe(projections: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in projections.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        rows.append(
            {
                "element_id": int(player.get("element") or 0),
                "element": int(player.get("element") or 0),
                "name": player.get("name"),
                "position": player.get("position"),
                "team_id": int(player.get("team_id") or 0),
                "now_cost": int(player.get("now_cost") or 0),
                "status": player.get("status"),
                "eligible": str(player.get("status") or "a") not in {"u"},
                # Full 20/25/30/25 producer is intentionally NOT invented here.
                "canonical_evaluation_complete": False,
            }
        )
    return [row for row in rows if row["element"] > 0]


def _lineup_content(lineup: Mapping[str, Any] | None) -> dict[str, Any]:
    if not lineup:
        return {"status": "UNAVAILABLE"}
    return {
        "formation": lineup.get("formation"),
        "starting_xi": lineup.get("starting_xi"),
        "bench": lineup.get("bench"),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "lineup_score": lineup.get("lineup_score"),
        "formation_comparison": lineup.get("formation_comparison"),
    }


def _section(
    state: str,
    content: Any,
    reason: str | None = None,
    *,
    available_count: int | None = None,
    expected_count: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"state": state, "content": content}
    if reason:
        row["degradation_reason"] = reason
    if available_count is not None:
        row["available_count"] = int(available_count)
    if expected_count is not None:
        row["expected_count"] = int(expected_count)
    return row


def run_deep(
    *,
    runtime_data_root: Path,
    report_slot: str,
    output_dir: Path,
    checkpoint_time: str | None = None,
) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    state = _read_json(STATE_PATH, {}) or {}

    prefetch = _stage(
        ledger,
        "V6_REPORT_PREFETCH_BINDING",
        lambda: _require_report_prefetch(
            runtime_data_root,
            report_slot=report_slot,
        ),
        required=True,
    )
    if not prefetch:
        raise IntegratedRunnerError(
            "DEEP integrated runner requires fresh same-occurrence V6 report-prefetch"
        )

    official = _stage(
        ledger,
        "V6_OFFICIAL_FACTS",
        lambda: _official_payload(runtime_data_root),
        required=True,
    )
    if not official:
        raise IntegratedRunnerError("required Official FPL factual input unavailable")
    bootstrap = official["bootstrap"]
    fixtures = official["fixtures"]
    planning_gw = _planning_gw(bootstrap)
    owned = _stage(
        ledger,
        "OUR15_IDENTITY",
        lambda: _owned15(runtime_data_root, state, bootstrap),
        required=True,
    )
    if not owned:
        raise IntegratedRunnerError("OUR15 unavailable")

    strength = _stage(
        ledger,
        "TEAM_STRENGTH",
        lambda: build_team_strength(bootstrap, fixtures),
        required=True,
    )
    projections = _stage(
        ledger,
        "P1_1_P1_3_FULL_UNIVERSE",
        lambda: build_player_projections(
            bootstrap,
            strength or {},
            planning_gw,
            {},
            horizon=5,
            player_features_payload={},
            player_match_rows=[],
            opponent_history_rows=[],
            opponent_history_scope="CURRENT-SEASON ONLY",
        ),
        required=True,
    )
    if not projections:
        raise IntegratedRunnerError("full-universe V12 projection stage unavailable")

    _stage(
        ledger,
        "OFFICIAL_ROLE_EVIDENCE",
        lambda: attach_official_role_evidence(projections, bootstrap),
    )
    _stage(
        ledger,
        "P1_6_TACTICAL_ROLE",
        lambda: attach_tactical_role_scores(
            projections,
            planning_gw,
            team_strength=strength or {},
        ),
    )

    owned_ids = {int(row["element_id"]) for row in owned}
    model_rows = _projection_model_rows(projections, owned_ids)
    all15 = _stage(
        ledger,
        "ALL15_MATERIALIZATION",
        lambda: materialize_all15(owned15=owned, model_rows=model_rows),
        required=True,
    )
    lineup = _stage(
        ledger,
        "P1_7_LINEUP",
        lambda: optimize_lineup(
            projections,
            sorted(owned_ids),
            planning_gw=planning_gw,
        ),
    )

    predictor = _read_json(
        runtime_data_root / "data/v6/current/official_price_predictor.json",
        {},
    ) or {}
    rise = _stage(
        ledger,
        "OFFICIAL_FPL_PREDICTOR_RISE20",
        lambda: build_price20(
            predictor_artifact=predictor,
            direction="RISE",
            owned_element_ids=sorted(owned_ids),
        ),
    )
    fall = _stage(
        ledger,
        "OFFICIAL_FPL_PREDICTOR_FALL20",
        lambda: build_price20(
            predictor_artifact=predictor,
            direction="FALL",
            owned_element_ids=sorted(owned_ids),
        ),
    )
    price_radar = _stage(
        ledger,
        "OUR15_PRICE_RADAR",
        lambda: build_actionable_price_radar(
            owned15=owned,
            predictor_artifact=predictor,
        ),
    )

    universe = _candidate_universe(projections)
    watchlist = _stage(
        ledger,
        "WATCHLIST20",
        lambda: build_watchlist20(
            evaluated_universe=universe,
            owned_element_ids=sorted(owned_ids),
            universe_authority="PARTIAL",
        ),
    )

    standings = _read_json(
        runtime_data_root / "data/v6/mini_leagues/9477/standings.json",
        {},
    ) or {}
    picks_gw = max(
        [
            int(path.name.split("_")[1])
            for path in (runtime_data_root / "data/v6/mini_leagues/9477").glob("gw_*_manager_picks.json")
            if path.name.startswith("gw_")
        ]
        or [max(1, planning_gw - 1)]
    )
    manager_picks = _read_json(
        runtime_data_root
        / f"data/v6/mini_leagues/9477/gw_{picks_gw}_manager_picks.json",
        {},
    ) or {}
    mini = _stage(
        ledger,
        "P1_8_MINI_LEAGUE_SNAPSHOT",
        lambda: build_mini_league_snapshot(
            standings,
            manager_picks,
            our_entry_id=3462711,
            planning_gw=planning_gw,
        ),
    )

    universe_gap = {
        "status": "PARTIAL",
        "reason": (
            "P1.1/P1.3/P1.6 executed for full universe, but the current repository "
            "does not yet expose V12-native numeric producers for all four "
            "20/25/30/25 components. Full football_score/ranking is therefore "
            "fail-closed instead of reconstructed ad hoc."
        ),
        "scanned_players": len(universe),
        "required_component_weights": {
            "PROVEN_HISTORICAL": 0.20,
            "TACTICAL_ROLE": 0.25,
            "CURRENT_UNDERLYING": 0.30,
            "FIXTURE_SECURITY": 0.25,
        },
    }
    ledger.append(
        {
            "stage": "CANONICAL_UNIVERSE_20_25_30_25",
            "status": "PARTIAL",
            "required": True,
            "reason": universe_gap["reason"],
        }
    )

    lineup_state = "COMPLETE" if lineup else "DEGRADED"
    lineup_reason = None if lineup else "P1.7 owner did not produce a supportable route"
    mini_state = (
        "COMPLETE"
        if mini and mini.get("coverage_state") == "FULL"
        else "DEGRADED"
    )
    mini_reason = (
        None
        if mini_state == "COMPLETE"
        else "ICON+ public coverage is incomplete for this occurrence"
    )
    watch_state = str((watchlist or {}).get("state") or "UNAVAILABLE")
    watch_reason = (watchlist or {}).get("degradation_reason") or universe_gap["reason"]

    sections = {
        "S01": _section(
            "COMPLETE",
            {
                "operational_state": "WAIT",
                "planning_gw": planning_gw,
                "report_slot": report_slot,
                "integrated_runner": "EXECUTED",
            },
        ),
        "S02": _section(
            "COMPLETE",
            {"rows": (all15 or {}).get("rows", [])},
            available_count=len((all15 or {}).get("rows", [])),
            expected_count=15,
        ),
        "S03": _section(
            "COMPLETE",
            {
                "decision_delta": "NO ACT WITHOUT FULL 20/25/30/25 UNIVERSE EVALUATION",
                "runner_delta": "P1.1/P1.3/P1.6/P1.7/price/ICON stages now occurrence-bound",
            },
        ),
        "S04": _section(
            "COMPLETE",
            {
                "changes": [
                    "Integrated owner-module execution is bound to one occurrence.",
                    "Manual prose is not accepted as an analytics substitute.",
                ]
            },
        ),
        "S05": _section(
            "COMPLETE",
            {
                "planning_gw": planning_gw,
                "fixtures": [
                    row for row in fixtures
                    if int(row.get("event") or -1) == planning_gw
                ],
                "weather": "DIRECT_CHATGPT_REQUIRED_AT_VISIBLE_DELIVERY",
            },
        ),
        "S06": _section(
            lineup_state,
            _lineup_content(lineup),
            lineup_reason,
        ),
        "S07": _section(
            lineup_state,
            {"main_starting_xi_battle": (lineup or {}).get("main_starting_xi_battle")},
            lineup_reason,
        ),
        "S08": _section(
            lineup_state,
            {
                "captain": (lineup or {}).get("captain"),
                "vice_captain": (lineup or {}).get("vice_captain"),
            },
            lineup_reason,
        ),
        "S09": _section(
            "DEGRADED",
            {"chip": "UNAVAILABLE_CURRENT_AUTH"},
            "private authenticated chip/economics evidence unavailable",
        ),
        "S10": _section(
            "COMPLETE" if price_radar else "DEGRADED",
            price_radar or {"rows": []},
            None if price_radar else "Official FPL predictor radar unavailable",
        ),
        "S11": _section(
            watch_state,
            {
                "rows": (watchlist or {}).get("rows", []),
                "universe_evaluator": universe_gap,
            },
            None if watch_state == "COMPLETE" else watch_reason,
            available_count=(watchlist or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S12": _section(
            str((rise or {}).get("state") or "UNAVAILABLE"),
            rise or {"rows": []},
            (rise or {}).get("degradation_reason"),
            available_count=(rise or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S13": _section(
            str((fall or {}).get("state") or "UNAVAILABLE"),
            fall or {"rows": []},
            (fall or {}).get("degradation_reason"),
            available_count=(fall or {}).get("available_count", 0),
            expected_count=20,
        ),
        "S14": _section(
            "DEGRADED",
            {
                "universe_scan": universe_gap,
                "package_routes": [],
                "monte_carlo": {
                    "execution_state": "NOT_RUN",
                    "reason": "FULL_20_25_30_25_UNIVERSE_EVALUATION_REQUIRED_FIRST",
                },
            },
            universe_gap["reason"],
        ),
        "S15": _section(
            "COMPLETE",
            {
                "evidence_quality": {
                    "official_fpl": "CURRENT_INPUT_READ",
                    "p1_1_p1_3": "EXECUTED",
                    "p1_6": "EXECUTED",
                    "p1_7": "EXECUTED" if lineup else "PARTIAL",
                    "price_predictor": (rise or {}).get("predictor_health"),
                    "universe_20_25_30_25": "PARTIAL",
                }
            },
        ),
        "S15B": _section(
            mini_state,
            mini or {"coverage_state": "UNAVAILABLE"},
            mini_reason,
        ),
        "S16": _section(
            "COMPLETE",
            {"rows": (all15 or {}).get("rows", [])},
            available_count=len((all15 or {}).get("rows", [])),
            expected_count=15,
        ),
        "S17": _section(
            "COMPLETE",
            {
                "engine_data_status": {
                    "runner": "V12_INTEGRATED_REPORT_RUNNER",
                    "planning_gw": planning_gw,
                    "projection_players": len(projections.get("players") or []),
                    "our15": len(owned),
                    "mini_league_coverage": (mini or {}).get("coverage_state"),
                    "stage_ledger": ledger,
                }
            },
        ),
        "S18": _section(
            "COMPLETE",
            {
                "NOW": "WAIT",
                "TRIGGER TO ACT": "FULL 20/25/30/25 universe evaluator + legal/economic route + robustness evidence",
                "ABORT / REVERSAL": "role/injury/economics or challenger evidence invalidates selected route",
                "NEXT CHECKPOINT": "next due report occurrence with fresh V6 prefetch",
            },
        ),
        "S19": _section(
            "COMPLETE",
            {
                "final_judgement": (
                    "WAIT pending full canonical universe component evaluation; "
                    "do not privilege prior shortlist names."
                )
            },
        ),
    }

    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=sections,
        checkpoint_time=checkpoint_time,
    )
    body = render_deep_text(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema": "FPL_MASTER_V12_INTEGRATED_REPORT_BUNDLE_V1",
        "authority": str(CANONICAL_PATH.relative_to(ROOT)),
        "state_authority": False,
        "report_mode": "DEEP",
        "report_slot": report_slot,
        "planning_gw": planning_gw,
        "stage_ledger": ledger,
        "report": report,
        "visible_body": body,
        "source_fingerprints": {
            "report_prefetch": _fingerprint(prefetch),
            "official_fpl": _fingerprint(official["payload"]),
            "state": _fingerprint(state),
            "predictor": _fingerprint(predictor),
            "mini_league_standings": _fingerprint(standings),
            "mini_league_picks": _fingerprint(manager_picks),
        },
        "governance": {
            "scheduler_created": False,
            "v6_mutated": False,
            "legacy_runtime_executed": False,
            "second_methodology_created": False,
            "manual_shortlist_privileged": False,
            "report_falls_back_to_prose_without_bundle": False,
        },
    }
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body, encoding="utf-8")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(
            {
                "report_slot": report_slot,
                "report_mode": "DEEP",
                "planning_gw": planning_gw,
                "stages": ledger,
                "bundle_fingerprint": _fingerprint(bundle),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--report-mode", default="DEEP")
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--checkpoint-time", default=None)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    mode = str(args.report_mode).upper()
    if mode not in SUPPORTED_MODES:
        raise IntegratedRunnerError(
            f"runner stage-1 supports {sorted(SUPPORTED_MODES)}; got {mode}"
        )
    run_deep(
        runtime_data_root=Path(args.runtime_data_root),
        report_slot=args.report_slot,
        output_dir=Path(args.output_dir),
        checkpoint_time=args.checkpoint_time,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
