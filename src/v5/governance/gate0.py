from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Any, Mapping

from src.v5.config_cache import load_json_config

CANONICAL_REGISTRY = "config/gate0_registry.json"
POLICY_REGISTRY = "config/v5_gate0_policy_registry.json"


@lru_cache(maxsize=1)
def _canonical_data() -> dict[str, Any]:
    data = load_json_config(CANONICAL_REGISTRY)
    if not isinstance(data.get("checks"), list) or not isinstance(data.get("contract"), dict):
        raise RuntimeError("invalid canonical Gate0 registry")
    return data


def _canonical() -> list[dict[str, Any]]:
    return _canonical_data()["checks"]


def _contract() -> dict[str, Any]:
    return _canonical_data()["contract"]


@lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    data = load_json_config(POLICY_REGISTRY)
    if not isinstance(data.get("affordability"), dict) or not isinstance(data.get("lineup"), dict):
        raise RuntimeError("invalid V5 Gate0 policy registry")
    return data


def _required_int(mapping: Mapping[str, Any], key: str, context: str) -> int:
    value = mapping.get(key)
    if value is None:
        raise RuntimeError(f"Gate0 missing required {context}.{key}")
    return int(value)


@lru_cache(maxsize=1)
def _row_map() -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in _canonical()}


def _phase_ids(phase: str) -> tuple[str, ...]:
    return tuple(str(row["id"]) for row in _canonical() if str(row.get("phase")) == phase)


def _expected_ids() -> set[str]:
    contract = _contract()
    count = _required_int(contract, "expected_count", "contract")
    first = _required_int(contract, "first_index", "contract")
    width = _required_int(contract, "zero_pad", "contract")
    prefix = str(contract.get("id_prefix") or "")
    if not prefix:
        raise RuntimeError("Gate0 contract.id_prefix is required")
    return {f"{prefix}{idx:0{width}d}" for idx in range(first, first + count)}


def _registry_integrity() -> dict[str, Any]:
    rows = _canonical()
    contract = _contract()
    expected_count = _required_int(contract, "expected_count", "contract")
    ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    expected_ids = _expected_ids()
    declared = set(ids)
    allowed_phases = {str(value) for value in contract.get("phases") or []}
    declared_phases = {str(row.get("phase")) for row in rows}
    phase_errors = sorted(phase for phase in declared_phases if phase not in allowed_phases)
    empty_phases = sorted(phase for phase in allowed_phases if not _phase_ids(phase))
    integrity_ok = bool(
        len(rows) == expected_count
        and not duplicates
        and declared == expected_ids
        and bool(allowed_phases)
        and not phase_errors
        and not empty_phases
    )
    return {
        "expected": expected_count,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "missing_ids": sorted(expected_ids - declared),
        "unexpected_ids": sorted(declared - expected_ids),
        "allowed_phases": sorted(allowed_phases),
        "phase_errors": phase_errors,
        "empty_phases": empty_phases,
        "integrity_ok": integrity_ok,
    }


def _result(check_id: str, passed: bool, detail: str, *, phase: str) -> dict[str, Any]:
    row = _row_map()[check_id]
    return {
        "id": check_id,
        "name": row.get("name"),
        "critical": bool(row.get("critical", True)),
        "phase": phase,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def _summary(items: list[dict[str, Any]], phase: str, ruleset_id: str | None) -> dict[str, Any]:
    counts = Counter(item["status"] for item in items)
    integrity = _registry_integrity()
    passed = bool(integrity["integrity_ok"] and counts.get("FAIL", 0) == 0)
    return {
        "phase": phase,
        "model": _policy().get("model_id"),
        "ruleset_id": ruleset_id,
        "pass": passed,
        "counts": dict(counts),
        "items": items,
        "registry_integrity": integrity,
    }


def _position_counts(squad: list[dict[str, Any]], expected: dict[str, int]) -> dict[str, int]:
    return {position: sum(str(player.get("position")) == position for player in squad) for position in expected}


def _ledger_reconciled(finance: dict[str, Any], squad: list[dict[str, Any]]) -> tuple[bool, str]:
    ledger = finance.get("players") if isinstance(finance.get("players"), list) else []
    squad_ids = {int(player.get("element") or -1) for player in squad}
    ledger_ids = {int(player.get("element") or -1) for player in ledger}
    complete = bool(finance.get("sell_value_complete"))
    sell_values_present = len(ledger) == len(squad) and all(row.get("sell_cost") is not None for row in ledger)
    calculated_sell = sum(int(row["sell_cost"]) for row in ledger) if sell_values_present else None
    declared_sell = finance.get("sell_value")
    total_matches = calculated_sell is not None and declared_sell is not None and int(declared_sell) == calculated_sell
    passed = complete and squad_ids == ledger_ids and sell_values_present and total_matches
    return passed, (
        f"complete={complete},squad_rows={len(squad)},ledger_rows={len(ledger)},"
        f"id_match={squad_ids == ledger_ids},declared_sell={declared_sell},calculated_sell={calculated_sell}"
    )


def _render_phase_results(
    phase: str,
    implementations: Mapping[str, tuple[bool, str]],
) -> list[dict[str, Any]]:
    items = []
    for check_id in _phase_ids(phase):
        passed, detail = implementations.get(check_id, (False, "no Gate0 implementation registered for canonical check"))
        items.append(_result(check_id, bool(passed), str(detail), phase=phase))
    return items


def preflight(truth: dict[str, Any]) -> dict[str, Any]:
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    squad_rules = rules.get("squad") if isinstance(rules.get("squad"), dict) else {}
    team = truth.get("team") if isinstance(truth.get("team"), dict) else {}
    squad = team.get("squad") if isinstance(team.get("squad"), list) else []
    validation = team.get("validation") if isinstance(team.get("validation"), dict) else {}
    finance = team.get("finance") if isinstance(team.get("finance"), dict) else {}
    expected_counts = {str(k): int(v) for k, v in (squad_rules.get("position_counts") or {}).items()}
    counts = _position_counts(squad, expected_counts)
    clubs = Counter(int(player.get("team_id") or -1) for player in squad)
    ids = [int(player.get("element") or -1) for player in squad]
    ledger_ok, ledger_detail = _ledger_reconciled(finance, squad)
    squad_size = _required_int(squad_rules, "squad_size", "rules.squad")
    max_per_club = _required_int(squad_rules, "max_players_per_club", "rules.squad")

    check_results = {
        "G0-01": (len(squad) == squad_size, f"count={len(squad)},expected={squad_size}"),
        "G0-02": (counts.get("GK") == expected_counts.get("GK"), f"GK={counts.get('GK')},expected={expected_counts.get('GK')}"),
        "G0-03": (counts.get("DEF") == expected_counts.get("DEF"), f"DEF={counts.get('DEF')},expected={expected_counts.get('DEF')}"),
        "G0-04": (counts.get("MID") == expected_counts.get("MID"), f"MID={counts.get('MID')},expected={expected_counts.get('MID')}"),
        "G0-05": (counts.get("FWD") == expected_counts.get("FWD"), f"FWD={counts.get('FWD')},expected={expected_counts.get('FWD')}"),
        "G0-07": (max(clubs.values(), default=0) <= max_per_club, f"max_club={max(clubs.values(), default=0)},limit={max_per_club}"),
        "G0-08": (len(ids) == len(set(ids)), f"unique={len(set(ids))},total={len(ids)}"),
        "G0-09": (bool(validation.get("passed")), f"team_validation={validation.get('passed')}"),
        "G0-15": (ledger_ok, ledger_detail),
    }
    return _summary(_render_phase_results("preflight", check_results), "preflight", rules.get("ruleset_id"))


def _lineup_check(decision: dict[str, Any], truth: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    lineup = decision.get("lineup") if isinstance(decision.get("lineup"), dict) else {}
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    lineup_rules = rules.get("lineup") if isinstance(rules.get("lineup"), dict) else {}
    starters = lineup.get("starters") if isinstance(lineup.get("starters"), list) else []
    bench = lineup.get("bench") if isinstance(lineup.get("bench"), list) else []
    starter_ids = {int(player.get("element") or -1) for player in starters}
    captain = lineup.get("captain") if isinstance(lineup.get("captain"), dict) else {}
    vice = lineup.get("vice_captain") if isinstance(lineup.get("vice_captain"), dict) else {}
    captain_id = int(captain.get("element") or -1)
    vice_id = int(vice.get("element") or -1)
    formation = str(lineup.get("formation") or "")
    starting_gks = sum(str(player.get("position")) == "GK" for player in starters)
    bench_gks = sum(str(player.get("position")) == "GK" for player in bench)
    bench_outfield = len(bench) - bench_gks
    expected_bench = lineup_rules.get("bench") if isinstance(lineup_rules.get("bench"), dict) else {}
    starting_size = _required_int(lineup_rules, "starting_xi_size", "rules.lineup")
    starting_goalkeepers = _required_int(lineup_rules, "starting_goalkeepers", "rules.lineup")
    bench_goalkeepers = _required_int(expected_bench, "goalkeepers", "rules.lineup.bench")
    bench_outfield_expected = _required_int(expected_bench, "outfield", "rules.lineup.bench")

    return {
        "G0-10": (
            lineup.get("status") == "READY" and formation in {str(x) for x in lineup_rules.get("legal_formations") or []},
            f"status={lineup.get('status')},formation={formation}",
        ),
        "G0-11": (
            len(starters) == starting_size and starting_gks == starting_goalkeepers,
            f"starters={len(starters)},expected={starting_size},starting_gk={starting_gks},expected_gk={starting_goalkeepers}",
        ),
        "G0-12": (
            captain_id in starter_ids and vice_id in starter_ids and captain_id != vice_id,
            f"captain={captain_id},vice={vice_id},captain_in_xi={captain_id in starter_ids},vice_in_xi={vice_id in starter_ids}",
        ),
        "G0-13": (
            len(bench) == bench_goalkeepers + bench_outfield_expected
            and bench_gks == bench_goalkeepers
            and bench_outfield == bench_outfield_expected,
            f"bench={len(bench)},GK={bench_gks}/{bench_goalkeepers},outfield={bench_outfield}/{bench_outfield_expected}",
        ),
    }


def _package_checks(decision: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    packages = decision.get("packages") if isinstance(decision.get("packages"), list) else []
    returned = packages if packages else ([decision.get("hold")] if isinstance(decision.get("hold"), dict) else [])
    affordability_policy = _policy()["affordability"]
    minimum_itb = _required_int(affordability_policy, "minimum_resulting_itb_tenths", "policy.affordability")
    affordability_rows = []
    legality_rows = []
    for package in returned:
        if not isinstance(package, dict):
            continue
        money = package.get("affordability") if isinstance(package.get("affordability"), dict) else {}
        resulting_itb = money.get("resulting_itb")
        affordable = resulting_itb is not None and int(resulting_itb) >= minimum_itb
        affordability_rows.append((str(package.get("id")), affordable, resulting_itb))
        legality_rows.append((str(package.get("id")), bool(package.get("legal")), affordable))
    affordability_pass = bool(affordability_rows) and all(row[1] for row in affordability_rows)
    revalidated_pass = bool(legality_rows) and all(row[1] and row[2] for row in legality_rows)
    return {
        "G0-06": (affordability_pass, f"minimum_itb={minimum_itb},packages={affordability_rows}"),
        "G0-16": (revalidated_pass, f"packages={legality_rows}"),
    }


def _chip_check(truth: dict[str, Any]) -> tuple[bool, str]:
    chip_policy = _policy().get("chip") or {}
    chip = truth.get("chip_state") if isinstance(truth.get("chip_state"), dict) else {}
    if not chip:
        required = bool(chip_policy.get("require_truth_chip_state", True))
        return (not required), f"truth chip_state unavailable;required={required}"
    max_active = _required_int(chip_policy, "maximum_active_chips", "policy.chip")
    active_count = int(chip.get("active_chip_count") or 0)
    passed = bool(chip.get("legal")) and active_count <= max_active
    return passed, (
        f"active_chip={chip.get('active_chip')},active_count={active_count},"
        f"max_active={max_active},legal={chip.get('legal')}"
    )


def postflight(truth: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    rules = truth.get("rules") if isinstance(truth.get("rules"), dict) else {}
    checks: dict[str, tuple[bool, str]] = {}
    checks.update(_package_checks(decision))
    checks.update(_lineup_check(decision, truth))
    checks["G0-14"] = _chip_check(truth)
    return _summary(_render_phase_results("postflight", checks), "postflight", rules.get("ruleset_id"))


def audit(truth: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    before = preflight(truth)
    after = postflight(truth, decision)
    items_by_id = {item["id"]: item for item in before["items"] + after["items"]}
    canonical_order = [str(row["id"]) for row in _canonical()]
    items = [items_by_id[check_id] for check_id in canonical_order if check_id in items_by_id]
    counts = Counter(item["status"] for item in items)
    integrity = _registry_integrity()
    expected_count = _required_int(_contract(), "expected_count", "contract")
    return {
        "phase": "full",
        "model": _policy().get("model_id"),
        "ruleset_id": (truth.get("rules") or {}).get("ruleset_id"),
        "pass": bool(integrity["integrity_ok"] and len(items) == expected_count and counts.get("FAIL", 0) == 0),
        "counts": dict(counts),
        "items": items,
        "preflight": before,
        "postflight": after,
        "registry_integrity": integrity,
    }
