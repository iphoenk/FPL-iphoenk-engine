from __future__ import annotations

import json
from typing import Any

from src.engines.base_state import bootstrap_maps, native_entry_summary, resolve_locked_player
from src.engines.team_value import build_transfer_spells, sell_cost
from src.models.transfer_state import build_transfer_state
from src.rules import CHIP_DISPLAY_NAMES, LINEUP_RULES, SQUAD_RULES, build_chip_ledger, ruleset_metadata
from src.settings import FAIL_CLOSED, PURCHASE_RECONSTRUCTION_BASELINE_GW, TEAM_ID
from src.utils import CONFIG, DATA, atomic_json, iso_now, parse_dt, read_json, utcnow

OFFICIAL = DATA / "official_snapshot.json"
TEAM_OUT = DATA / "team.json"
CHIPS_OUT = DATA / "chips.json"

CANONICAL_USER_CAPTURE_AUTHORITY = "LOCKED_PRE_DEADLINE"
OFFICIAL_SUBMITTED_AUTHORITY = "OFFICIAL_SUBMITTED"
USER_CAPTURE_CONTRACT = "STRUCTURED_USER_CAPTURE_V1"


def _validate_squad(squad: list[dict[str, Any]], by_id: dict[int, dict[str, Any]], teams: dict[int, str]) -> None:
    expected_size = int(SQUAD_RULES["squad_size"])
    expected_counts = {str(key): int(value) for key, value in dict(SQUAD_RULES["position_counts"]).items()}
    if len(squad) != expected_size:
        raise RuntimeError(f"FAIL CLOSED: squad count {len(squad)} expected {expected_size}")
    counts = {position: sum(1 for row in squad if row["position"] == position) for position in expected_counts}
    if counts != expected_counts:
        raise RuntimeError(f"FAIL CLOSED: position counts {counts} expected {expected_counts}")
    ids = [int(row["element"]) for row in squad]
    if len(ids) != len(set(ids)):
        raise RuntimeError("FAIL CLOSED: duplicate player in squad")
    club_counts: dict[str, int] = {}
    for row in squad:
        player = by_id[int(row["element"])]
        club = teams[int(player["team"])]
        club_counts[club] = club_counts.get(club, 0) + 1
    limit = int(SQUAD_RULES["max_players_per_club"])
    if max(club_counts.values(), default=0) > limit:
        raise RuntimeError(f"FAIL CLOSED: club limit exceeded {club_counts}; max={limit}")


def _capture_element_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("element", value.get("id"))
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _capture_lineup_validation(
    lock: dict[str, Any],
    squad: list[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    positions: dict[int, str],
) -> dict[str, Any]:
    payload = dict(lock)
    if isinstance(lock.get("lineup"), dict):
        payload.update(lock["lineup"])

    tracked = {
        "starting_xi",
        "bench",
        "bench_gk",
        "bench_order",
        "captain",
        "vice_captain",
        "active_chip",
        "chip",
    }
    supplied = any(key in payload for key in tracked)
    if not supplied:
        return {"status": "NOT_SUPPLIED", "valid": True, "errors": []}

    errors: list[str] = []
    squad_ids = {int(row["element"]) for row in squad}
    starting_ids: list[int] | None = None
    bench_ids: list[int] | None = None

    if "starting_xi" in payload:
        raw = payload.get("starting_xi")
        if not isinstance(raw, list):
            errors.append("starting_xi_not_list")
        else:
            parsed = [_capture_element_id(value) for value in raw]
            if any(value is None for value in parsed):
                errors.append("starting_xi_invalid_element")
            else:
                starting_ids = [int(value) for value in parsed if value is not None]
                if len(starting_ids) != int(LINEUP_RULES["starting_xi_size"]):
                    errors.append("starting_xi_wrong_size")
                if len(starting_ids) != len(set(starting_ids)):
                    errors.append("starting_xi_duplicate")
                if not set(starting_ids).issubset(squad_ids):
                    errors.append("starting_xi_not_subset_of_squad")
                if not errors:
                    xi_positions = [
                        positions[int(by_id[element]["element_type"])]
                        for element in starting_ids
                    ]
                    if xi_positions.count("GK") != int(LINEUP_RULES["starting_goalkeepers"]):
                        errors.append("starting_xi_goalkeeper_count")
                    formation = (
                        f"{xi_positions.count('DEF')}-"
                        f"{xi_positions.count('MID')}-"
                        f"{xi_positions.count('FWD')}"
                    )
                    if formation not in set(LINEUP_RULES["legal_formations"]):
                        errors.append("starting_xi_illegal_formation")

    if "bench" in payload:
        raw_bench = payload.get("bench")
        if not isinstance(raw_bench, list):
            errors.append("bench_not_list")
        else:
            parsed_bench = [_capture_element_id(value) for value in raw_bench]
            if any(value is None for value in parsed_bench):
                errors.append("bench_invalid_element")
            else:
                bench_ids = [int(value) for value in parsed_bench if value is not None]
    elif "bench_gk" in payload or "bench_order" in payload:
        bench_gk = _capture_element_id(payload.get("bench_gk"))
        raw_order = payload.get("bench_order")
        if bench_gk is None or not isinstance(raw_order, list):
            errors.append("bench_structure_incomplete")
        else:
            parsed_order = [_capture_element_id(value) for value in raw_order]
            if any(value is None for value in parsed_order):
                errors.append("bench_invalid_element")
            else:
                bench_ids = [bench_gk, *[int(value) for value in parsed_order if value is not None]]

    if bench_ids is not None:
        expected_bench = int((LINEUP_RULES.get("bench") or {}).get("goalkeepers") or 1) + int(
            (LINEUP_RULES.get("bench") or {}).get("outfield") or 3
        )
        if len(bench_ids) != expected_bench:
            errors.append("bench_wrong_size")
        if len(bench_ids) != len(set(bench_ids)):
            errors.append("bench_duplicate")
        if not set(bench_ids).issubset(squad_ids):
            errors.append("bench_not_subset_of_squad")
        valid_bench_ids = [element for element in bench_ids if element in by_id]
        bench_positions = [positions[int(by_id[element]["element_type"])] for element in valid_bench_ids]
        if len(valid_bench_ids) == len(bench_ids) and bench_positions.count("GK") != int(
            (LINEUP_RULES.get("bench") or {}).get("goalkeepers") or 1
        ):
            errors.append("bench_goalkeeper_count")

    if starting_ids is not None and bench_ids is not None:
        if set(starting_ids) & set(bench_ids):
            errors.append("starting_xi_bench_overlap")
        if set(starting_ids) | set(bench_ids) != squad_ids:
            errors.append("starting_xi_bench_do_not_cover_squad")

    captain = _capture_element_id(payload.get("captain")) if "captain" in payload else None
    vice = _capture_element_id(payload.get("vice_captain")) if "vice_captain" in payload else None
    if "captain" in payload and captain is None:
        errors.append("captain_invalid_element")
    if "vice_captain" in payload and vice is None:
        errors.append("vice_captain_invalid_element")
    if captain is not None and captain not in squad_ids:
        errors.append("captain_not_in_squad")
    if vice is not None and vice not in squad_ids:
        errors.append("vice_captain_not_in_squad")
    if captain is not None and vice is not None and captain == vice:
        errors.append("captain_equals_vice")
    if starting_ids is not None:
        if captain is not None and captain not in set(starting_ids):
            errors.append("captain_not_in_starting_xi")
        if vice is not None and vice not in set(starting_ids):
            errors.append("vice_captain_not_in_starting_xi")

    chip_value = payload.get("active_chip", payload.get("chip"))
    if chip_value is not None:
        normalized_chip = str(chip_value).strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {str(value).lower() for value in CHIP_DISPLAY_NAMES}
        if normalized_chip not in allowed:
            errors.append("invalid_chip")
        if bool(lock.get("wildcard_active")) and normalized_chip != "wildcard":
            errors.append("wildcard_flag_chip_mismatch")
        if bool(lock.get("free_hit_active")) and normalized_chip != "free_hit":
            errors.append("free_hit_flag_chip_mismatch")

    return {
        "status": "VALID" if not errors else "INVALID",
        "valid": not errors,
        "errors": errors,
    }


def validate_user_capture(
    lock: dict[str, Any],
    phase: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    teams: dict[int, str],
    positions: dict[int, str],
    *,
    now: Any = None,
) -> dict[str, Any]:
    """Validate evidence for an exact-GW structured own-team capture.

    Phase/scope rejection is resolved before this function is called. This
    validator therefore focuses on provenance, own-team identity, legal squad,
    optional lineup/captaincy/chip evidence, and finance precision metadata.
    """

    errors: list[str] = []
    current_time = now or utcnow()
    locked_at = parse_dt(lock.get("locked_at"))
    deadline = parse_dt(phase.get("deadline_time"))
    timestamp_valid = bool(
        locked_at is not None
        and deadline is not None
        and locked_at <= deadline
        and locked_at <= current_time
    )
    if not timestamp_valid:
        errors.append("invalid_or_missing_capture_timestamp")

    provenance = str(lock.get("authority_source") or "").strip()
    provenance_valid = bool(provenance)
    if not provenance_valid:
        errors.append("missing_capture_provenance")

    try:
        own_team = int(lock.get("team_id")) == int(TEAM_ID)
    except (TypeError, ValueError):
        own_team = False
    if not own_team:
        errors.append("capture_not_for_configured_own_team")

    squad: list[dict[str, Any]] = []
    identity_validated = True
    raw_players = lock.get("players")
    if not isinstance(raw_players, list):
        raw_players = []
        identity_validated = False
        errors.append("capture_players_not_list")

    if len(raw_players) != int(SQUAD_RULES["squad_size"]):
        errors.append("capture_wrong_squad_size")

    seen: set[int] = set()
    for row in raw_players:
        if not isinstance(row, dict):
            identity_validated = False
            errors.append("capture_player_not_object")
            continue
        try:
            player = resolve_locked_player(row, by_id, teams, positions)
        except (RuntimeError, TypeError, ValueError, KeyError) as exc:
            identity_validated = False
            errors.append(f"official_identity_resolution_failed:{exc}")
            continue
        element = int(player["id"])
        if element in seen:
            errors.append("capture_duplicate_player")
        seen.add(element)
        squad.append(
            {
                "element": element,
                "name": player["web_name"],
                "position": positions[player["element_type"]],
                "purchase_cost": row.get("purchase_cost"),
                "source": "user_capture_exact" if row.get("purchase_cost") is not None else "user_capture",
            }
        )

    squad_legal = False
    if identity_validated and len(squad) == int(SQUAD_RULES["squad_size"]):
        try:
            _validate_squad(squad, by_id, teams)
            squad_legal = True
        except RuntimeError as exc:
            errors.append(f"illegal_capture_squad:{exc}")
    elif "capture_wrong_squad_size" not in errors:
        errors.append("capture_squad_identity_incomplete")

    lineup = _capture_lineup_validation(lock, squad, by_id, positions) if squad_legal else {
        "status": "NOT_EVALUATED",
        "valid": False,
        "errors": ["squad_not_legal"],
    }
    if not lineup.get("valid"):
        errors.extend(str(value) for value in lineup.get("errors") or [])

    purchase_count = sum(
        1
        for row in raw_players
        if isinstance(row, dict) and row.get("purchase_cost") is not None
    )
    valid = not errors and identity_validated and squad_legal and bool(lineup.get("valid"))
    return {
        "contract": USER_CAPTURE_CONTRACT,
        "status": "VALID" if valid else "INVALID",
        "valid": valid,
        "errors": errors,
        "provenance": provenance or None,
        "capture_timestamp": lock.get("locked_at"),
        "timestamp_valid": timestamp_valid,
        "own_team": own_team,
        "identity_validated": identity_validated,
        "squad_legal": squad_legal,
        "lineup": lineup,
        "purchase_cost_rows_supplied": purchase_count,
        "purchase_cost_exact_for_all": purchase_count == int(SQUAD_RULES["squad_size"]),
    }


def projection_baseline_authority(
    lock: dict[str, Any],
    phase: dict[str, Any],
    *,
    capture_validation: dict[str, Any] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Resolve the phase-scoped authority for the planning squad.

    Public Official submitted picks are the default. A structured user capture
    can become authority only for its exact target GW while that target is
    genuinely pre-deadline and its evidence contract is valid.
    """

    planning_gw = int(phase.get("planning_gw") or phase.get("current_gw") or 0) or None
    submitted_gw = int(phase.get("submitted_gw") or 0) or None
    wildcard = bool(lock.get("wildcard_active"))
    free_hit = bool(lock.get("free_hit_active"))
    manual = bool(lock.get("planning_override_active"))
    override_requested = wildcard or free_hit or manual

    target_raw = lock.get("target_gw")
    try:
        target_gw = int(target_raw) if target_raw is not None else None
    except (TypeError, ValueError):
        target_gw = None
    if override_requested and target_gw is None:
        raise RuntimeError("FAIL CLOSED: active planning squad override requires valid target_gw")

    current_time = now or utcnow()
    deadline = parse_dt(phase.get("deadline_time"))
    pre_deadline = bool(
        planning_gw is not None
        and planning_gw != submitted_gw
        and (deadline is None or deadline > current_time)
    )
    exact_target = bool(
        override_requested
        and target_gw is not None
        and planning_gw is not None
        and target_gw == planning_gw
    )
    evidence_required = bool(override_requested and exact_target and pre_deadline)
    evidence_valid = bool((capture_validation or {}).get("valid")) if capture_validation is not None else True

    if wildcard:
        override_kind = "WILDCARD"
    elif free_hit:
        override_kind = "FREE_HIT"
    elif manual:
        override_kind = "USER_LOCK"
    else:
        override_kind = "NONE"

    rejection_reason = None
    if override_requested:
        if planning_gw is None:
            rejection_reason = "PLANNING_GW_UNAVAILABLE"
        elif target_gw < planning_gw:
            rejection_reason = "STALE_TARGET_GW"
        elif target_gw > planning_gw:
            rejection_reason = "WRONG_FUTURE_TARGET_GW"
        elif planning_gw == submitted_gw:
            rejection_reason = "POST_DEADLINE_OFFICIAL_RECLAIM"
        elif not pre_deadline:
            rejection_reason = "NOT_PRE_DEADLINE_PHASE"
        elif capture_validation is not None and not evidence_valid:
            rejection_reason = "INVALID_CAPTURE_EVIDENCE"

    override_applied = bool(
        override_requested
        and rejection_reason is None
        and exact_target
        and pre_deadline
        and evidence_valid
    )
    authority = CANONICAL_USER_CAPTURE_AUTHORITY if override_applied else OFFICIAL_SUBMITTED_AUTHORITY
    return {
        "planning_gw": planning_gw,
        "baseline_gw": submitted_gw,
        "default_rule": "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD",
        "default_authority": OFFICIAL_SUBMITTED_AUTHORITY,
        "override_requested": override_requested,
        "override_kind": override_kind,
        "override_target_gw": target_gw,
        "override_applied": override_applied,
        "effective_authority": authority,
        "authority_source": (
            str(lock.get("authority_source") or "")
            if override_applied
            else "OFFICIAL_FPL_PICKS"
        ),
        "canonical_user_capture_authority": CANONICAL_USER_CAPTURE_AUTHORITY,
        "capture_contract": USER_CAPTURE_CONTRACT,
        "capture_pre_deadline_phase": pre_deadline,
        "capture_target_gw_matches": exact_target,
        "capture_evidence_required": evidence_required,
        "capture_evidence": capture_validation,
        "capture_rejection_reason": rejection_reason,
        "stale_override_rejected": bool(
            override_requested
            and target_gw is not None
            and planning_gw is not None
            and target_gw < planning_gw
            and not override_applied
        ),
        "wrong_gw_override_rejected": bool(
            override_requested
            and target_gw is not None
            and planning_gw is not None
            and target_gw != planning_gw
            and not override_applied
        ),
        "post_deadline_official_reclaims_authority": bool(
            override_requested
            and target_gw == planning_gw
            and planning_gw == submitted_gw
            and not override_applied
        ),
    }


def run() -> dict[str, Any]:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap")
    phase = official.get("phase") or {}
    teams, positions, by_id = bootstrap_maps(bootstrap)
    entry = official.get("entry") or {}
    history = official.get("history") or {}
    transfers = list(official.get("transfers") or [])
    picks = official.get("picks") or {}
    health = official.get("endpoint_health") or {}

    lock = read_json(CONFIG / "locked_squad.json", {})
    authority_now = utcnow()
    preliminary = projection_baseline_authority(lock, phase, now=authority_now)
    capture_validation = None
    if preliminary.get("capture_evidence_required"):
        capture_validation = validate_user_capture(
            lock,
            phase,
            by_id,
            teams,
            positions,
            now=authority_now,
        )
    projection_baseline = projection_baseline_authority(
        lock,
        phase,
        capture_validation=capture_validation,
        now=authority_now,
    )
    use_lock = bool(projection_baseline.get("override_applied"))

    squad: list[dict[str, Any]] = []
    if use_lock:
        seen: set[int] = set()
        for row in lock.get("players") or []:
            player = resolve_locked_player(row, by_id, teams, positions)
            element = int(player["id"])
            if element in seen:
                raise RuntimeError(f"FAIL CLOSED: duplicate locked element ID {element}")
            seen.add(element)
            exact_purchase = row.get("purchase_cost") is not None
            squad.append(
                {
                    "element": element,
                    "name": player["web_name"],
                    "position": positions[player["element_type"]],
                    "purchase_cost": row.get("purchase_cost"),
                    "source": "user_capture_exact" if exact_purchase else "user_capture",
                    "purchase_cost_exact": exact_purchase,
                }
            )
    elif picks:
        for pick in picks.get("picks") or []:
            player = by_id.get(int(pick["element"]))
            if player:
                squad.append(
                    {
                        "element": int(player["id"]),
                        "name": player["web_name"],
                        "position": positions[player["element_type"]],
                        "source": "official_picks",
                        "purchase_cost_exact": False,
                    }
                )

    if FAIL_CLOSED:
        _validate_squad(squad, by_id, teams)

    spells = build_transfer_spells(transfers)
    baseline = official.get("purchase_baseline") or {}
    baseline_gw = int(baseline.get("gw") or PURCHASE_RECONSTRUCTION_BASELINE_GW)
    baseline_ids = {
        int(row["element"])
        for row in ((baseline.get("picks") or {}).get("picks") or [])
    }
    ledger: list[dict[str, Any]] = []
    for row in squad:
        player = by_id[int(row["element"])]
        purchase = row.get("purchase_cost")
        purchase_source = row.get("source")
        purchase_exact = bool(row.get("purchase_cost_exact"))
        if purchase is None:
            spell = spells.get(int(player["id"])) or {}
            if spell.get("purchase_cost") is not None:
                purchase = spell["purchase_cost"]
                purchase_source = "entry/transfers"
            elif int(player["id"]) in baseline_ids:
                purchase = int(player["now_cost"]) - int(player.get("cost_change_start") or 0)
                purchase_source = f"gw{baseline_gw}_reconstruction"
        ledger.append(
            {
                "element": int(player["id"]),
                "name": player["web_name"],
                "team": teams[int(player["team"])],
                "position": positions[player["element_type"]],
                "purchase_cost": purchase,
                "now_cost": int(player["now_cost"]),
                "sell_cost": sell_cost(int(player["now_cost"]), purchase)
                if purchase is not None
                else None,
                "purchase_source": purchase_source,
                "finance_precision": "EXACT_USER_CAPTURE"
                if purchase_exact
                else ("RECONSTRUCTED_OR_OFFICIAL" if purchase is not None else "UNKNOWN"),
                "ownership": player.get("selected_by_percent"),
                "status": player.get("status"),
            }
        )

    fetched_at = (health.get("entry") or {}).get("fetched_at")
    entry_summary = native_entry_summary(entry, fetched_at)
    used_chips = list(history.get("chips") or [])
    planning_gw = int(phase.get("planning_gw") or phase.get("current_gw") or 1)
    chip_ledger = build_chip_ledger(used_chips, planning_gw)
    ruleset = ruleset_metadata()
    transfer_state = build_transfer_state(
        lock=lock,
        projection_baseline=projection_baseline,
        entry=entry,
        history=history,
        transfers=transfers,
        planning_gw=planning_gw,
        submitted_gw=phase.get("submitted_gw"),
    )
    itb = lock.get("itb_tenths") if use_lock else entry.get("last_deadline_bank")
    totals = {
        "market_value": sum(int(row["now_cost"]) for row in ledger),
        "sell_value": sum(
            int(row["sell_cost"])
            for row in ledger
            if row.get("sell_cost") is not None
        ),
        "itb": itb,
    }
    authority = str(projection_baseline.get("effective_authority"))
    generated_at = iso_now()
    team = {
        "generated_at": generated_at,
        "team_id": TEAM_ID,
        "entry": entry_summary,
        "squad_authority": authority,
        "projection_baseline": projection_baseline,
        "transfer_state": transfer_state,
        "squad": squad,
        "team_value_ledger": ledger,
        "totals": totals,
        "governance": {
            "ruleset_id": ruleset["id"],
            "sell_value_formula_owned_by_team_value_engine": True,
            "transfer_state_owned_by_team_state": True,
            "transfer_hit_rule_registry_owned": True,
            "current_private_transfer_state_not_inferred_from_public_absence": True,
            "squad_identity_is_element_id_authoritative": True,
            "purchase_reconstruction_baseline_gw": baseline_gw,
            "planning_override_must_target_exact_gw": True,
            "structured_user_capture_contract": USER_CAPTURE_CONTRACT,
            "canonical_applied_user_capture_authority": CANONICAL_USER_CAPTURE_AUTHORITY,
            "capture_can_override_private_own_team_state_only": True,
            "official_public_player_facts_remain_authoritative": True,
            "capture_finance_exact_only_when_explicitly_supplied": True,
            "stale_planning_override_is_rejected": True,
            "post_deadline_official_submission_reclaims_authority": True,
        },
    }
    chips = {
        "generated_at": generated_at,
        "used": used_chips,
        "ledger": chip_ledger,
        "ruleset_id": ruleset["id"],
    }
    atomic_json(TEAM_OUT, team)
    atomic_json(CHIPS_OUT, chips)
    return team


if __name__ == "__main__":
    out = run()
    print(
        json.dumps(
            {
                "team_id": out.get("team_id"),
                "squad_authority": out.get("squad_authority"),
                "projection_baseline": out.get("projection_baseline"),
                "transfer_state": out.get("transfer_state"),
                "players": len(out.get("team_value_ledger") or []),
                "totals": out.get("totals"),
            },
            ensure_ascii=False,
        )
    )
