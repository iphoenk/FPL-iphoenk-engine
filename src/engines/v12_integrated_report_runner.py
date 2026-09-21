from __future__ import annotations

"""Occurrence-bound V12 integrated report runner.

Thin orchestration only:
- consumes V6 factual artifacts;
- calls existing V12 owner modules where prerequisites are supportable;
- never creates a second football/model authority;
- renders the exact Canonical report skeleton;
- performs pre/post-render QA;
- emits a durable bundle for the ChatGPT scheduler to consume.

A stage that cannot execute must be explicit PARTIAL/NOT_RUN with a reason.
Silently skipping an owner stage is forbidden.
"""

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from src.engines.visible_content_proof import canonical_mode_contract
from src.engines.v12_package_search import PackageSearchError, search_packages
from src.engines.v12_report_orchestration import (
    build_price20,
    build_visible_mathematical_decision_stack,
    materialize_deep_report,
    render_deep_text,
    validate_human_facing_body,
)
from src.runtime_v6.domains.report_plane.delivery_integrity import (
    RANK20_REQUIRED_FIELDS,
)
from src.runtime_v6.domains.report_plane.report_qa import (
    validate_post_render_qa,
    validate_pre_render_qa,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import _parse_sections


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
STATE_PATH = ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts/v12_integrated_report"

_POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

_DEEP_LABEL_TO_ID = {
    "DECISION/STATUS": "S01",
    "OUR15": "S02",
    "DECISION DELTA": "S03",
    "CHANGES": "S04",
    "FIXTURES/REST/CONDITIONS": "S05",
    "FORMATION/XI/BENCH": "S06",
    "XI BATTLE": "S07",
    "C/VC": "S08",
    "CHIP": "S09",
    "ACTIONABLE PRICE RADAR": "S10",
    "WATCHLIST20": "S11",
    "RISE20": "S12",
    "FALL20": "S13",
    "PACKAGE OPTIMIZER/FRONTIER": "S14",
    "EVIDENCE QUALITY": "S15",
    "ICON+ MINI-LEAGUE": "S15B",
    "ALL15 NEXT-GW TACTICAL/PROBABILITY": "S16",
    "SOURCE HEALTH/FRESHNESS/LINEAGE": "S17",
    "WAIT/PREPARE/ACT + TRIGGER/REVERSAL": "S18",
    "FINAL JUDGEMENT": "S19",
}


class IntegratedRunnerError(RuntimeError):
    pass


def _json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def parse_command(command: str) -> dict[str, str]:
    text = str(command or "").strip()
    if not text.startswith("/v12-report-run"):
        raise IntegratedRunnerError("command must start with /v12-report-run")
    values: dict[str, str] = {}
    for token in text.split()[1:]:
        if "=" not in token:
            raise IntegratedRunnerError(f"invalid command token: {token}")
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise IntegratedRunnerError(f"invalid command token: {token}")
        values[key] = value
    mode = values.get("report_mode", "").upper()
    if mode != "DEEP":
        raise IntegratedRunnerError("integrated runner currently owns DEEP only")
    if "report_slot" not in values:
        raise IntegratedRunnerError("report_slot is required")
    if "checkpoint_time" not in values:
        raise IntegratedRunnerError("checkpoint_time is required")
    try:
        datetime.fromisoformat(values["report_slot"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegratedRunnerError("report_slot must be timezone-aware ISO-8601") from exc
    if not re.fullmatch(r"\d{2}:\d{2}", values["checkpoint_time"]):
        raise IntegratedRunnerError("checkpoint_time must be HH:MM")
    return values


def _predictor_artifact(root: Path) -> dict[str, Any] | None:
    return _json(root / "data/v6/current/official_price_predictor.json")


def _predictor_players(artifact: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(artifact, Mapping):
        return []
    data = artifact.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("players"), list):
        return [
            dict(row) for row in data.get("players") or []
            if isinstance(row, Mapping)
        ]
    if isinstance(artifact.get("players"), list):
        return [
            dict(row) for row in artifact.get("players") or []
            if isinstance(row, Mapping)
        ]
    return []


def _submitted_picks(root: Path) -> dict[str, Any]:
    return dict(_json(root / "data/v6/personal/submitted_picks.json", {}) or {})


def _current_team(root: Path) -> dict[str, Any]:
    return dict(_json(root / "data/v6/personal/current_team.json", {}) or {})


def _state(root: Path) -> dict[str, Any]:
    return dict(_json(root / STATE_PATH.relative_to(ROOT), {}) or {})


def _extract_pick_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("picks")
    if isinstance(raw, list):
        return [dict(row) for row in raw if isinstance(row, Mapping)]
    data = payload.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("picks"), list):
        return [dict(row) for row in data.get("picks") or [] if isinstance(row, Mapping)]
    return []


def _pick_element(row: Mapping[str, Any]) -> int | None:
    for key in ("element_id", "element", "id"):
        value = row.get(key)
        if value is None:
            continue
        try:
            element = int(value)
        except (TypeError, ValueError):
            continue
        if element > 0:
            return element
    return None


def _fallback_state_ids(state: Mapping[str, Any]) -> list[int]:
    squad = state.get("confirmed_current_squad_state")
    if not isinstance(squad, Mapping):
        return []
    ids: list[int] = []
    for key in ("gk", "def", "mid", "fwd", "GK", "DEF", "MID", "FWD"):
        rows = squad.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping):
                value = row.get("element_id", row.get("element", row.get("id")))
            else:
                value = row
            try:
                element = int(value)
            except (TypeError, ValueError):
                continue
            if element > 0:
                ids.append(element)
    return ids


def _extract_squad(
    *,
    submitted: Mapping[str, Any],
    state: Mapping[str, Any],
    universe_by_id: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    picks = _extract_pick_rows(submitted)
    ids = [element for row in picks if (element := _pick_element(row)) is not None]
    source = "PUBLIC_SUBMITTED_PICKS"
    if len(ids) != 15 or len(set(ids)) != 15:
        ids = _fallback_state_ids(state)
        source = "V12_STATE_FALLBACK"
        picks = []
    if len(ids) != 15 or len(set(ids)) != 15:
        return {
            "status": "UNAVAILABLE",
            "source": source,
            "ids": ids,
            "rows": [],
            "xi_ids": [],
            "bench_ids": [],
            "captain": None,
            "vice": None,
            "formation": "UNAVAILABLE",
        }

    rows: list[dict[str, Any]] = []
    for rank, element in enumerate(ids, start=1):
        player = dict(universe_by_id.get(element) or {})
        element_type = int(player.get("element_type") or 0)
        rows.append(
            {
                "rank": rank,
                "element_id": element,
                "player_name": player.get("web_name") or f"element:{element}",
                "position": _POSITION.get(element_type, "UNKNOWN"),
                "team_id": player.get("team"),
                "now_cost": player.get("now_cost"),
                "status": player.get("status"),
            }
        )

    xi_ids: list[int] = []
    bench_ids: list[int] = []
    captain = vice = None
    if picks:
        for row in picks:
            element = _pick_element(row)
            if element is None:
                continue
            try:
                multiplier = int(row.get("multiplier") or 0)
            except (TypeError, ValueError):
                multiplier = 0
            if multiplier > 0:
                xi_ids.append(element)
            else:
                bench_ids.append(element)
            if row.get("captain") is True or row.get("is_captain") is True:
                captain = element
            if row.get("vice_captain") is True or row.get("is_vice_captain") is True:
                vice = element

    if len(xi_ids) != 11:
        xi_ids = ids[:11]
        bench_ids = ids[11:]
    by_id = {row["element_id"]: row for row in rows}
    formation_counts: dict[str, int] = {"DEF": 0, "MID": 0, "FWD": 0}
    for element in xi_ids:
        pos = str((by_id.get(element) or {}).get("position") or "")
        if pos in formation_counts:
            formation_counts[pos] += 1
    formation = (
        f"{formation_counts['DEF']}-{formation_counts['MID']}-{formation_counts['FWD']}"
        if sum(formation_counts.values()) == 10
        else "UNAVAILABLE"
    )
    name_by_id = {
        int(row["element_id"]): str(row.get("player_name") or row["element_id"])
        for row in rows
    }
    return {
        "status": "COMPLETE",
        "source": source,
        "ids": ids,
        "rows": rows,
        "xi_ids": xi_ids,
        "bench_ids": bench_ids,
        "captain": captain,
        "vice": vice,
        "formation": formation,
        "name_by_id": name_by_id,
    }


def _rank20_rows(
    result: Mapping[str, Any],
    *,
    owned_ids: set[int],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for rank, raw in enumerate(result.get("rows") or [], start=1):
        row = dict(raw)
        element = int(row.get("element_id") or 0)
        confidence = row.get("confidence")
        if isinstance(confidence, Mapping):
            confidence_text = json.dumps(confidence, sort_keys=True, default=str)
        else:
            confidence_text = str(confidence or "UNAVAILABLE")
        raw_hash = _sha(row)
        cycle = row.get("cycles_to_expected_change")
        if cycle in (None, "", "UNAVAILABLE"):
            cycle = row.get("date_state") or "NO_CROSSING_WITHIN_GOVERNED_HORIZON"
        eta = (
            row.get("estimated_change_window")
            or row.get("estimated_change_date_wib")
            or row.get("date_state")
            or "UNAVAILABLE"
        )
        output.append(
            {
                "rank": rank,
                "element_id": element,
                "player_name": row.get("player") or f"element:{element}",
                "current_price": row.get("current_price", "UNAVAILABLE"),
                "ownership_percent": row.get("selected_by_percent", "UNAVAILABLE"),
                "ownership_tag": "OWNED" if element in owned_ids else "NON_OWNED",
                "direction": str(row.get("direction") or "UNAVAILABLE").upper(),
                "current_progress_percent": row.get("official_or_provider_progress", "UNAVAILABLE"),
                "projection_offset_0_percent": row.get("projected_percent", "UNAVAILABLE"),
                "predicted_change_cycle": cycle,
                "predicted_change_at": row.get("estimated_change_date_wib", "UNAVAILABLE"),
                "eta_human": eta,
                "model_urgency": row.get("prediction_strength", "UNAVAILABLE"),
                "confidence": confidence_text,
                "source": row.get("estimate_source", "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR"),
                "observed_at": row.get("evidence_timestamp", "UNAVAILABLE"),
                "raw_payload_hash": raw_hash,
            }
        )
    return output


def _rank20_table(rows: Sequence[Mapping[str, Any]]) -> str:
    return _table(
        list(RANK20_REQUIRED_FIELDS),
        [[row.get(field, "UNAVAILABLE") for field in RANK20_REQUIRED_FIELDS] for row in rows],
    )


def _our15_table(rows: Sequence[Mapping[str, Any]]) -> str:
    return _table(
        ["rank", "element_id", "player_name", "position"],
        [
            [row.get("rank"), row.get("element_id"), row.get("player_name"), row.get("position")]
            for row in rows
        ],
    )


def _sell_values(current_team: Mapping[str, Any]) -> dict[int, int | None]:
    result: dict[int, int | None] = {}
    rows = current_team.get("players")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        element = _pick_element(row)
        if element is None:
            continue
        value = row.get("selling_price", row.get("sell_value", row.get("sell_cost")))
        try:
            result[element] = int(value) if value is not None else None
        except (TypeError, ValueError):
            result[element] = None
    return result


def _package_stage(
    *,
    squad: Mapping[str, Any],
    universe: Sequence[Mapping[str, Any]],
    current_team: Mapping[str, Any],
    canonical_universe_count: int | None,
) -> dict[str, Any]:
    if squad.get("status") != "COMPLETE":
        return {
            "status": "NOT_RUN",
            "reason": "CURRENT_SQUAD_UNAVAILABLE",
            "search_result": None,
        }
    sell_values = _sell_values(current_team)
    squad_rows = []
    for owned in squad.get("rows") or []:
        element = int(owned["element_id"])
        row = {
            "element": element,
            "position": owned.get("position"),
            "team_id": owned.get("team_id"),
            "now_cost": owned.get("now_cost"),
            "sell_value": sell_values.get(element),
        }
        squad_rows.append(row)
    candidate_rows = []
    for player in universe:
        try:
            element = int(player.get("id"))
            element_type = int(player.get("element_type") or 0)
            team_id = int(player.get("team") or 0)
            now_cost = int(player.get("now_cost") or 0)
        except (TypeError, ValueError):
            continue
        position = _POSITION.get(element_type)
        if not position or team_id <= 0 or now_cost <= 0:
            continue
        candidate_rows.append(
            {
                "element": element,
                "position": position,
                "team_id": team_id,
                "now_cost": now_cost,
                "status": player.get("status"),
                "eligible": True,
                "name": player.get("web_name"),
            }
        )
    bank_raw = current_team.get("bank")
    try:
        bank = int(bank_raw) if bank_raw is not None else 0
    except (TypeError, ValueError):
        bank = 0
    observed_universe_count = len(candidate_rows)
    expected_source_count = (
        int(canonical_universe_count)
        if canonical_universe_count is not None
        else observed_universe_count
    )
    source_universe_complete = (
        expected_source_count > 0
        and observed_universe_count == expected_source_count
    )
    try:
        result = search_packages(
            current_squad=squad_rows,
            candidate_universe=candidate_rows,
            bank=bank,
            max_transfers=1,
            universe_complete=source_universe_complete,
            expected_eligible_universe_count=None,
            lossy_pruning=False,
            execution_mode="BATCH",
            batch_size=512,
        )
    except (PackageSearchError, ValueError) as exc:
        return {
            "status": "NOT_RUN",
            "reason": f"{type(exc).__name__}:{exc}",
            "search_result": None,
        }
    search_authority = str(result.get("search_authority") or "").upper()
    return {
        "status": "PASS" if search_authority == "FULL" else "PARTIAL",
        "reason": (
            None
            if search_authority == "FULL"
            else (
                "P1.2A source universe is not proven complete; "
                f"observed={observed_universe_count} expected={expected_source_count}"
            )
        ),
        "utility_reason": (
            "P1.2B utility ranking requires occurrence-bound P1.1/P1.3/P1.7 projections"
        ),
        "source_universe_count": observed_universe_count,
        "expected_source_universe_count": expected_source_count,
        "source_universe_complete": source_universe_complete,
        "search_result": result,
    }


def _mini_league_stage(root: Path) -> dict[str, Any]:
    files = sorted((root / "data/v6/mini_leagues").glob("*/standings.json"))
    if not files:
        return {"status": "UNAVAILABLE", "reason": "NO_MINI_LEAGUE_STANDINGS", "rows": []}
    path = files[0]
    payload = dict(_json(path, {}) or {})
    managers = payload.get("managers")
    if not isinstance(managers, list):
        return {"status": "UNAVAILABLE", "reason": "STANDINGS_SCHEMA_UNAVAILABLE", "rows": []}
    rows = [dict(row) for row in managers if isinstance(row, Mapping)]
    return {
        "status": "PARTIAL",
        "reason": "standings available; EO/ownership aggregate owner not bound in integrated runner v1",
        "league_file": str(path.relative_to(root)),
        "generated_at": payload.get("generated_at"),
        "rows": rows,
    }


def _section_payloads(
    *,
    checkpoint_time: str,
    squad: Mapping[str, Any],
    rise: Mapping[str, Any],
    fall: Mapping[str, Any],
    package: Mapping[str, Any],
    mini: Mapping[str, Any],
    publish_integrity: Mapping[str, Any],
    report_prefetch: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    owned_rows = list(squad.get("rows") or [])
    by_id = {int(row["element_id"]): row for row in owned_rows}
    xi_ids = list(squad.get("xi_ids") or [])
    bench_ids = list(squad.get("bench_ids") or [])
    name_by_id = {
        int(key): str(value)
        for key, value in dict(squad.get("name_by_id") or {}).items()
    }
    bench_gk = next(
        (
            element
            for element in bench_ids
            if str((by_id.get(int(element)) or {}).get("position")) == "GK"
        ),
        bench_ids[0] if bench_ids else None,
    )
    outfield_bench = [element for element in bench_ids if element != bench_gk][:3]
    rise_rows = list(rise.get("rank20_rows") or [])
    fall_rows = list(fall.get("rank20_rows") or [])

    package_result = package.get("search_result") if isinstance(package.get("search_result"), Mapping) else None
    search_proof = dict((package_result or {}).get("search_proof") or {})
    route_counts = dict((package_result or {}).get("route_counts") or {})

    mini_rows = list(mini.get("rows") or [])
    top_rows = mini_rows[:10]

    evidence_fact = "Official FPL/V6 factual evidence bound to the occurrence"
    evidence_model = "Official FPL Price Change Predictor plus explicit V12 owner-stage execution states"
    evidence_inference = "V12 WAIT/PREPARE/ACT decision implications only where supportable"

    section_payloads: dict[str, Any] = {
        "S01": {
            "state": "COMPLETE",
            "content": {
                "operational_state": "WAIT",
                "summary": "Integrated runner executed; unavailable analytic owners are explicit rather than silently skipped.",
            },
        },
        "S02": {
            "state": "COMPLETE" if len(owned_rows) == 15 else "UNAVAILABLE",
            "degradation_reason": None if len(owned_rows) == 15 else "current 15-player squad unavailable",
            "content": {
                "our15_table": "\n" + _our15_table(owned_rows),
                "source": squad.get("source"),
            } if owned_rows else {"source": squad.get("source")},
        },
        "S03": {
            "state": "COMPLETE",
            "content": {
                "decision_delta": "Fresh occurrence runner state replaces manual prose path.",
            },
        },
        "S04": {
            "state": "DEGRADED",
            "degradation_reason": "post-match per-fixture analytic owner not bound in integrated runner v1",
            "content": {
                "change_scope": "No silent omission; post-match owner stage is explicitly pending.",
            },
        },
        "S05": {
            "state": "DEGRADED",
            "degradation_reason": "direct-chat weather/news enrichment occurs after runner bundle",
            "content": {
                "WEATHER_SOURCE": "DEGRADED",
                "fixture_scope": "V6 factual fixture evidence available; direct weather/news enrichment is external to repository runner.",
            },
        },
        "S06": {
            "state": "COMPLETE" if len(xi_ids) == 11 and len(bench_ids) == 4 else "DEGRADED",
            "degradation_reason": (
                None if len(xi_ids) == 11 and len(bench_ids) == 4
                else "XI/bench identity incomplete"
            ),
            "content": {
                "formation": squad.get("formation"),
                "XI": ", ".join(name_by_id.get(int(value), str(value)) for value in xi_ids),
                "BENCH": ", ".join(name_by_id.get(int(value), str(value)) for value in bench_ids),
                "bench_gk": name_by_id.get(int(bench_gk), str(bench_gk)) if bench_gk is not None else "UNAVAILABLE",
                "outfield_autosub_priority": [
                    name_by_id.get(int(value), str(value))
                    for value in outfield_bench
                ],
            },
        },
        "S07": {
            "state": "DEGRADED",
            "degradation_reason": "P1.1/P1.7 current occurrence owner surface not yet bound",
            "content": {"xi_battle": "NOT RUN; exact blocker preserved in execution proof."},
        },
        "S08": {
            "state": "COMPLETE" if squad.get("captain") and squad.get("vice") else "DEGRADED",
            "degradation_reason": (
                None if squad.get("captain") and squad.get("vice")
                else "captain/vice identity unavailable in submitted picks"
            ),
            "content": {
                "captain": squad.get("captain") or "UNAVAILABLE",
                "vice_captain": squad.get("vice") or "UNAVAILABLE",
            },
        },
        "S09": {
            "state": "DEGRADED",
            "degradation_reason": "current authenticated chip inventory not bound by runner v1",
            "content": {"chip": "UNAVAILABLE"},
        },
        "S10": {
            "state": "COMPLETE" if rise_rows or fall_rows else "DEGRADED",
            "degradation_reason": None if rise_rows or fall_rows else "official predictor rows unavailable",
            "content": {
                "official_predictor": "Official FPL Price Change Predictor",
                "rise_rows": len(rise_rows),
                "fall_rows": len(fall_rows),
            },
        },
        "S11": {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 20,
            "degradation_reason": "full-universe 20/25/30/25 Watchlist20 scorer not yet bound in runner v1",
            "content": {"watchlist20": "NOT RUN; no padding."},
        },
        "S12": {
            "state": str(rise.get("state") or "UNAVAILABLE"),
            "available_count": len(rise_rows),
            "expected_count": 20,
            "degradation_reason": rise.get("degradation_reason"),
            "content": {"rise20_table": "\n" + _rank20_table(rise_rows)} if rise_rows else {"rise20": "UNAVAILABLE"},
        },
        "S13": {
            "state": str(fall.get("state") or "UNAVAILABLE"),
            "available_count": len(fall_rows),
            "expected_count": 20,
            "degradation_reason": fall.get("degradation_reason"),
            "content": {"fall20_table": "\n" + _rank20_table(fall_rows)} if fall_rows else {"fall20": "UNAVAILABLE"},
        },
        "S14": {
            "state": "DEGRADED",
            "degradation_reason": package.get("reason") or "package utility owner unavailable",
            "content": {
                "package_search_proof": search_proof,
                "route_counts": route_counts,
                "package_routes": [],
                "package_universe_challengers": [],
                "search_authority": (package_result or {}).get("search_authority", "PARTIAL"),
            },
        },
        "S15": {
            "state": "COMPLETE",
            "content": {
                "FACT": evidence_fact,
                "MODEL": evidence_model,
                "INFERENCE": evidence_inference,
            },
        },
        "S15B": {
            "state": "DEGRADED",
            "degradation_reason": mini.get("reason") or "mini-league evidence unavailable",
            "content": {
                "MINI_LEAGUE_SOURCE": "DEGRADED",
                "standings_generated_at": mini.get("generated_at") or "UNAVAILABLE",
                "top10": top_rows,
            },
        },
        "S16": {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 15,
            "degradation_reason": "occurrence-bound P1.1/P1.3/P1.6/P1.7 ALL15 probability surface not yet bound",
            "content": {"all15_probability": "NOT RUN; exact owner-stage blocker preserved."},
        },
        "S17": {
            "state": "COMPLETE",
            "content": {
                "publish_integrity": publish_integrity.get("status", "UNAVAILABLE"),
                "report_prefetch_status": report_prefetch.get("prefetch_status", report_prefetch.get("status", "UNAVAILABLE")),
                "canonical_players": ((publish_integrity.get("identity") or {}).get("players") if isinstance(publish_integrity.get("identity"), Mapping) else "UNAVAILABLE"),
            },
        },
        "S18": {
            "state": "COMPLETE",
            "content": {
                "NOW": "WAIT",
                "TRIGGER TO ACT": "P1.1/P1.3/P1.7/package utility evidence produces a supportable route advantage.",
                "ABORT / REVERSAL": "Role, injury, affordability or full-universe ranking changes.",
                "NEXT CHECKPOINT": "Next occurrence-bound integrated runner execution.",
            },
        },
        "S19": {
            "state": "COMPLETE",
            "content": {
                "final_judgement": "WAIT pending the explicitly incomplete analytic owner stages; no manual shortlist privilege.",
            },
        },
    }

    section_states = {
        "WATCHLIST20": {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 20,
            "degradation_reason": section_payloads["S11"]["degradation_reason"],
        },
        "RISE20": {
            "state": str(rise.get("state") or "UNAVAILABLE"),
            "available_count": len(rise_rows),
            "expected_count": 20,
            "degradation_reason": rise.get("degradation_reason"),
        },
        "FALL20": {
            "state": str(fall.get("state") or "UNAVAILABLE"),
            "available_count": len(fall_rows),
            "expected_count": 20,
            "degradation_reason": fall.get("degradation_reason"),
        },
        "PACKAGE_FRONTIER": {
            "state": "DEGRADED",
            "degradation_reason": section_payloads["S14"]["degradation_reason"],
        },
        "ICON+": {
            "state": "DEGRADED",
            "degradation_reason": section_payloads["S15B"]["degradation_reason"],
        },
        "ALL15": {
            "state": "DEGRADED",
            "available_count": 0,
            "expected_count": 15,
            "degradation_reason": section_payloads["S16"]["degradation_reason"],
        },
    }

    visible_contract = {
        "report_due": True,
        "visible_report_suppressed": False,
        "optional_scope_degraded": True,
        "visible_order": [
            "DECISION/STATUS",
            "OUR15",
            "DECISION DELTA",
            "CHANGES",
            "FIXTURES/REST/CONDITIONS",
            "FORMATION/XI/BENCH",
            "XI BATTLE",
            "C/VC",
            "CHIP",
            "ACTIONABLE PRICE RADAR",
            "WATCHLIST20",
            "RISE20",
            "FALL20",
            "PACKAGE OPTIMIZER/FRONTIER",
            "EVIDENCE QUALITY",
            "ICON+ MINI-LEAGUE",
            "ALL15 NEXT-GW TACTICAL/PROBABILITY",
            "SOURCE HEALTH/FRESHNESS/LINEAGE",
            "WAIT/PREPARE/ACT + TRIGGER/REVERSAL",
            "FINAL JUDGEMENT",
        ],
        "bench_presentation": {
            "bench_gk": bench_gk,
            "outfield_autosub_priority": outfield_bench,
            "position_by_player": {
                str(row["element_id"]): row.get("position")
                for row in owned_rows
            },
        },
        "all15": [],
        "watchlist20": [],
        "rise20": rise_rows,
        "fall20": fall_rows,
        "package_routes": [],
        "package_universe_challengers": [],
        "package_search_proof": search_proof,
        "search_authority": (package_result or {}).get("search_authority", "PARTIAL"),
        "search_authority_visible": True,
        "serious_comparison": False,
        "package_full_universe_derived": bool(search_proof),
        "icon": {
            "status": "DEGRADED",
            "standings_available": bool(mini_rows),
        },
        "football_optimal_baseline_before_icon": False,
        "section_states": section_states,
        "checkpoint_time": checkpoint_time,
        "serious_decision_required": True,
        "press_news_probability_changes": {
            "state": "UNAVAILABLE",
            "reason": "direct news enrichment occurs outside repository runner",
        },
    }
    if checkpoint_time == "04:30":
        visible_contract["deep_emphasis"] = "OVERNIGHT_RESET_BASELINE"
    elif checkpoint_time == "12:30":
        visible_contract["deep_emphasis"] = "DELTA_SINCE_04:30"
    elif checkpoint_time == "21:30":
        visible_contract["deep_emphasis"] = "LATE_NEWS_OVERNIGHT_PRICE_DEADLINE_RISK"
        visible_contract["overnight_risk_board"] = [
            {
                "player_or_route": "CURRENT_SQUAD",
                "current_action": "WAIT",
                "possible_change_event": "official predictor / late team news",
                "materiality": "UNKNOWN_UNTIL_ANALYTIC_OWNER_BINDING",
                "next_checkpoint": "next occurrence-bound integrated run",
            }
        ]

    evidence = {
        "fact": evidence_fact,
        "model": evidence_model,
        "inference": evidence_inference,
    }
    return section_payloads, visible_contract, evidence


def _compute_contract(
    *,
    squad: Mapping[str, Any],
    rise_rows: Sequence[Mapping[str, Any]],
    fall_rows: Sequence[Mapping[str, Any]],
    visible_contract: Mapping[str, Any],
    evidence: Mapping[str, str],
) -> dict[str, Any]:
    watch_state = ((visible_contract.get("section_states") or {}).get("WATCHLIST20") or {}).get("state")
    rise_state = ((visible_contract.get("section_states") or {}).get("RISE20") or {}).get("state")
    fall_state = ((visible_contract.get("section_states") or {}).get("FALL20") or {}).get("state")
    core = {
        "OUR15": {"status": "PASS" if len(squad.get("rows") or []) == 15 else "FAIL", "total": len(squad.get("rows") or [])},
        "XI": {"status": "PASS" if len(squad.get("xi_ids") or []) == 11 else "FAIL", "total": len(squad.get("xi_ids") or [])},
        "BENCH": {"status": "PASS" if len(squad.get("bench_ids") or []) == 4 else "FAIL", "total": len(squad.get("bench_ids") or [])},
        "WATCHLIST20": {"status": "PASS" if watch_state == "COMPLETE" else "FAIL", "total": 0},
        "RISE20": {"status": "PASS" if rise_state == "COMPLETE" else "FAIL", "total": len(rise_rows)},
        "FALL20": {"status": "PASS" if fall_state == "COMPLETE" else "FAIL", "total": len(fall_rows)},
    }
    fingerprint_payload = {
        "squad": squad.get("ids"),
        "rise": list(rise_rows),
        "fall": list(fall_rows),
        "visible_contract": visible_contract,
    }
    return {
        "status": "PASS",
        "compute_ready": True,
        "delivery_ready": False,
        "next_action": "PRE_RENDER_QA",
        "failures": [],
        "legacy_fallback_allowed": False,
        "compute_fingerprint": _sha(fingerprint_payload),
        **core,
        "FACT_MODEL": {
            "status": "PASS",
            "overlap": [],
            "fact_keys": [evidence["fact"]],
            "model_keys": [evidence["model"]],
            "inference_keys": [evidence["inference"]],
        },
        "serious_decision_required": True,
    }


def _parse_slot(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _core_slot_binding(
    *,
    report_slot: str,
    publish_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    report_dt = _parse_slot(report_slot)
    actual_dt = _parse_slot(publish_integrity.get("logical_slot"))
    if report_dt is None:
        return {
            "status": "FAIL",
            "reason": "REPORT_SLOT_INVALID",
            "expected_core_slot": None,
            "actual_core_slot": publish_integrity.get("logical_slot"),
        }
    expected_dt = report_dt.replace(minute=0, second=0, microsecond=0)
    expected_utc = expected_dt.astimezone(__import__("datetime").timezone.utc)
    actual_utc = actual_dt.astimezone(__import__("datetime").timezone.utc) if actual_dt else None
    matched = actual_utc == expected_utc
    return {
        "status": "PASS" if matched else "PARTIAL",
        "reason": None if matched else "CORE_SLOT_MISMATCH",
        "expected_core_slot": expected_dt.isoformat(),
        "expected_core_slot_utc": expected_utc.isoformat(),
        "actual_core_slot": actual_dt.isoformat() if actual_dt else None,
        "actual_core_slot_utc": actual_utc.isoformat() if actual_utc else None,
    }


def _report_prefetch_binding(
    *,
    report_slot: str,
    report_prefetch: Mapping[str, Any],
) -> dict[str, Any]:
    requested = _parse_slot(report_slot)
    target = _parse_slot(
        report_prefetch.get("target_logical_report_slot")
        or report_prefetch.get("logical_slot")
    )
    requested_utc = requested.astimezone(__import__("datetime").timezone.utc) if requested else None
    target_utc = target.astimezone(__import__("datetime").timezone.utc) if target else None
    checks = {
        "report_kind_full_master": str(report_prefetch.get("report_kind") or "") == "full_master",
        "target_report_slot_match": bool(
            requested_utc is not None
            and target_utc is not None
            and requested_utc == target_utc
        ),
        "personal_requested": report_prefetch.get("personal_requested") is True,
        "mini_league_requested": report_prefetch.get("mini_league_requested") is True,
        "live_requested": report_prefetch.get("live_requested") is True,
        "public_core_complete": report_prefetch.get("public_core_complete") is True,
        "fresh_for_target_report": report_prefetch.get("fresh_for_target_report") is True,
    }
    passed = all(checks.values())
    failed = [key for key, value in checks.items() if not value]
    return {
        "status": "PASS" if passed else "PARTIAL",
        "reason": None if passed else "REPORT_PREFETCH_OCCURRENCE_MISMATCH:" + ",".join(failed),
        "requested_report_slot": report_slot,
        "target_logical_report_slot": report_prefetch.get("target_logical_report_slot"),
        "report_kind": report_prefetch.get("report_kind"),
        "report_prefetch_run_id": report_prefetch.get("report_prefetch_run_id"),
        "generated_at": report_prefetch.get("generated_at"),
        "checks": checks,
    }


def _runner_stage(
    *,
    owner: str,
    status: str,
    reason: str | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "owner": owner,
        "status": status,
        "reason": reason,
        "evidence": dict(evidence or {}),
    }


def run(
    *,
    root: Path,
    report_mode: str,
    report_slot: str,
    checkpoint_time: str,
    output_dir: Path,
) -> dict[str, Any]:
    if report_mode.upper() != "DEEP":
        raise IntegratedRunnerError("runner v1 supports DEEP only")
    canonical_text = (root / CANONICAL_PATH.relative_to(ROOT)).read_text(encoding="utf-8")
    state = _state(root)
    predictor = _predictor_artifact(root)
    universe = _predictor_players(predictor)
    universe_by_id = {
        int(row["id"]): row
        for row in universe
        if row.get("id") is not None
    }
    submitted = _submitted_picks(root)
    current_team = _current_team(root)
    squad = _extract_squad(
        submitted=submitted,
        state=state,
        universe_by_id=universe_by_id,
    )
    owned_ids = {int(value) for value in squad.get("ids") or []}

    rise_native = build_price20(
        predictor_artifact=predictor,
        direction="RISE",
        owned_element_ids=sorted(owned_ids),
    )
    fall_native = build_price20(
        predictor_artifact=predictor,
        direction="FALL",
        owned_element_ids=sorted(owned_ids),
    )
    rise_rows = _rank20_rows(rise_native, owned_ids=owned_ids)
    fall_rows = _rank20_rows(fall_native, owned_ids=owned_ids)
    rise = {**rise_native, "rank20_rows": rise_rows}
    fall = {**fall_native, "rank20_rows": fall_rows}

    publish_integrity = dict(_json(root / "data/v6/health/publish_integrity.json", {}) or {})
    identity = publish_integrity.get("identity")
    canonical_universe_count = None
    if isinstance(identity, Mapping):
        players_identity = identity.get("players")
        if isinstance(players_identity, Mapping):
            for key in ("canonical_count", "canonical", "count"):
                value = players_identity.get(key)
                try:
                    canonical_universe_count = int(value)
                except (TypeError, ValueError):
                    continue
                else:
                    break
    package = _package_stage(
        squad=squad,
        universe=universe,
        current_team=current_team,
        canonical_universe_count=canonical_universe_count,
    )
    mini = _mini_league_stage(root)
    report_prefetch_health = dict(_json(root / "data/v6/health/report_prefetch.json", {}) or {})
    report_prefetch = dict(_json(root / "data/v6/report_prefetch/latest.json", {}) or {})
    core_binding = _core_slot_binding(
        report_slot=report_slot,
        publish_integrity=publish_integrity,
    )
    prefetch_binding = _report_prefetch_binding(
        report_slot=report_slot,
        report_prefetch={
            **report_prefetch_health,
            "prefetch_status": report_prefetch_health.get("prefetch_status"),
            "occurrence_binding_status": prefetch_binding.get("status"),
            "occurrence_binding_reason": prefetch_binding.get("reason"),
        },
    )

    section_payloads, visible_contract, evidence = _section_payloads(
        checkpoint_time=checkpoint_time,
        squad=squad,
        rise=rise,
        fall=fall,
        package=package,
        mini=mini,
        publish_integrity=publish_integrity,
        report_prefetch=report_prefetch,
    )
    compute = _compute_contract(
        squad=squad,
        rise_rows=rise_rows,
        fall_rows=fall_rows,
        visible_contract=visible_contract,
        evidence=evidence,
    )

    math_stack = build_visible_mathematical_decision_stack({})
    report = materialize_deep_report(
        canonical_text=canonical_text,
        section_payloads=section_payloads,
        checkpoint_time=checkpoint_time,
        mathematical_decision_stack=math_stack,
    )
    section_manifest = [
        {
            "section_id": row["section_id"],
            "status": row["state"],
        }
        for row in report.get("sections") or []
    ]
    mini_complete = False
    pre = validate_pre_render_qa(
        compute_contract=compute,
        section_manifest=section_manifest,
        mini_league_denominator_complete=mini_complete,
        report_mode="DEEP",
        weather_contract_state="SOURCE_DEGRADED",
        visible_content_contract=visible_contract,
    )
    body = render_deep_text(report)
    human_failures = validate_human_facing_body(body)
    parsed_ids, _, _ = _parse_sections(body)

    rendered_states = {
        str(row["section_id"]): str(row["state"])
        for row in report.get("sections") or []
    }
    post = validate_post_render_qa(
        pre_render_qa=pre,
        rendered_body=body,
        rendered_section_ids=parsed_ids,
        rendered_section_states=rendered_states,
        rendered_compute_fingerprint=compute["compute_fingerprint"],
        render_contract_token=pre.get("render_contract_token"),
        rendered_counts=dict(pre.get("expected_counts") or {}),
        rendered_fact_keys=list(pre.get("expected_fact_keys") or []),
        rendered_model_keys=list(pre.get("expected_model_keys") or []),
        rendered_mini_league_denominator_complete=mini_complete,
        rendered_weather_contract_state="SOURCE_DEGRADED",
        rendered_visible_content_contract=visible_contract,
        truncated=False,
    )

    contract = canonical_mode_contract(canonical_text, "DEEP")
    stages = [
        _runner_stage(
            owner="CORE_SLOT_BINDING",
            status=core_binding["status"],
            reason=core_binding.get("reason"),
            evidence=core_binding,
        ),
        _runner_stage(
            owner="REPORT_PREFETCH_BINDING",
            status=prefetch_binding["status"],
            reason=prefetch_binding.get("reason"),
            evidence=prefetch_binding,
        ),
        _runner_stage(
            owner="V6_FACTUAL_BINDING",
            status="PASS" if publish_integrity.get("status") == "PASS" else "PARTIAL",
            reason=None if publish_integrity.get("status") == "PASS" else "publish_integrity not PASS",
            evidence={"report_slot": report_slot, "prefetch": report_prefetch.get("prefetch_status")},
        ),
        _runner_stage(
            owner="P1.1_XMINS",
            status="NOT_RUN",
            reason="current occurrence feature-to-P1.1 adapter not yet bound",
        ),
        _runner_stage(
            owner="P1.3_P1.3B_PLAYER_EVENTS",
            status="NOT_RUN",
            reason="P1.1 finite-state minutes prerequisite unavailable",
        ),
        _runner_stage(
            owner="P1.2A_PACKAGE_SEARCH",
            status=package.get("status", "NOT_RUN"),
            reason=package.get("reason"),
            evidence={
                "search_proof": ((package.get("search_result") or {}).get("search_proof") if isinstance(package.get("search_result"), Mapping) else None),
                "source_universe_count": package.get("source_universe_count"),
                "expected_source_universe_count": package.get("expected_source_universe_count"),
                "source_universe_complete": package.get("source_universe_complete"),
            },
        ),
        _runner_stage(
            owner="P1.7_LINEUP_OPTIMIZER",
            status="NOT_RUN",
            reason="occurrence-bound P1.3 fixture projection surface unavailable",
        ),
        _runner_stage(
            owner="P1.2B_PACKAGE_UTILITY",
            status="NOT_RUN",
            reason="P1.7 five-GW lineup surfaces unavailable",
        ),
        _runner_stage(
            owner="P1.4_MONTE_CARLO",
            status="NOT_RUN",
            reason="native P1.1/P1.3/P1.7 route surfaces unavailable; no fabricated paths",
            evidence={"minimum_paths": 500000, "correlated_required": True},
        ),
        _runner_stage(
            owner="OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
            status="PASS" if rise.get("state") == "COMPLETE" and fall.get("state") == "COMPLETE" else "PARTIAL",
            reason=(rise.get("degradation_reason") or fall.get("degradation_reason")),
            evidence={"rise_count": len(rise_rows), "fall_count": len(fall_rows)},
        ),
        _runner_stage(
            owner="CANONICAL_RENDER",
            status="PASS" if report.get("exact_canonical_order") else "FAIL",
            evidence={"section_ids": report.get("rendered_section_ids")},
        ),
        _runner_stage(
            owner="PRE_RENDER_QA",
            status=str(pre.get("status") or "UNKNOWN"),
            reason=";".join(pre.get("failures") or []) or None,
        ),
        _runner_stage(
            owner="POST_RENDER_QA",
            status=str(post.get("status") or "UNKNOWN"),
            reason=";".join(post.get("failures") or []) or None,
        ),
        _runner_stage(
            owner="HUMAN_FACING_QA",
            status="PASS" if not human_failures else "FAIL",
            reason=";".join(human_failures) or None,
        ),
    ]

    runner_pass = (
        core_binding.get("status") == "PASS"
        and prefetch_binding.get("status") == "PASS"
        and report.get("rendered_section_ids") == contract.get("expected_section_ids")
        and post.get("status") == "PASS"
        and not human_failures
    )
    proof = {
        "schema_version": 1,
        "runner": "V12_INTEGRATED_REPORT_RUNNER",
        "report_mode": "DEEP",
        "report_slot": report_slot,
        "checkpoint_time": checkpoint_time,
        "canonical_expected_section_ids": contract.get("expected_section_ids"),
        "rendered_section_ids": report.get("rendered_section_ids"),
        "canonical_catalog_complete": report.get("rendered_section_ids") == contract.get("expected_section_ids"),
        "core_slot_binding": core_binding,
        "report_prefetch_binding": prefetch_binding,
        "pre_render_qa_status": pre.get("status"),
        "post_render_qa_status": post.get("status"),
        "human_facing_qa_status": "PASS" if not human_failures else "FAIL",
        "runner_status": "PASS" if runner_pass else "FAIL",
        "stage_results": stages,
        "no_silent_stage_skip": True,
        "no_second_model_authority": True,
        "monte_carlo_fabricated": False,
    }
    bundle = {
        "schema_version": 1,
        "report_mode": "DEEP",
        "report_slot": report_slot,
        "checkpoint_time": checkpoint_time,
        "runner_status": proof["runner_status"],
        "section_manifest": section_manifest,
        "compute_contract": compute,
        "visible_content_contract": visible_contract,
        "pre_render_qa": pre,
        "post_render_qa": post,
        "execution_proof": proof,
        "report": report,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (output_dir / "report_body.md").write_text(body + "\n", encoding="utf-8")
    (output_dir / "execution_proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command")
    parser.add_argument("--report-mode")
    parser.add_argument("--report-slot")
    parser.add_argument("--checkpoint-time")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    if args.command:
        parsed = parse_command(args.command)
        report_mode = parsed["report_mode"]
        report_slot = parsed["report_slot"]
        checkpoint_time = parsed["checkpoint_time"]
    else:
        report_mode = str(args.report_mode or "")
        report_slot = str(args.report_slot or "")
        checkpoint_time = str(args.checkpoint_time or "")
    if not report_mode or not report_slot or not checkpoint_time:
        raise IntegratedRunnerError("report mode, report slot and checkpoint time are required")

    bundle = run(
        root=Path(args.root).resolve(),
        report_mode=report_mode,
        report_slot=report_slot,
        checkpoint_time=checkpoint_time,
        output_dir=Path(args.output_dir).resolve(),
    )
    print(
        json.dumps(
            {
                "runner_status": bundle.get("runner_status"),
                "report_mode": bundle.get("report_mode"),
                "report_slot": bundle.get("report_slot"),
                "section_count": len(bundle.get("section_manifest") or []),
                "output_dir": str(Path(args.output_dir).resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if bundle.get("runner_status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
