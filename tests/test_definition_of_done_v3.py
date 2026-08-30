import json
from pathlib import Path

from src.runtime_v3.definition_of_done import (
    _selected_profile_runtime_contract,
    _tactical_report_coverage,
)


SLO_PATH = Path("config/runtime/performance_slo.json")


def _runtime(profile: str, wall_ms: float) -> dict:
    slo = json.loads(SLO_PATH.read_text(encoding="utf-8"))
    cfg = slo["profiles"][profile]
    target = float(cfg["target_wall_ms"])
    ceiling = float(cfg.get("legacy_ceiling_ms") or target)
    return {
        "execution_profile": profile,
        "total_wall_ms": wall_ms,
        "target_wall_ms": target,
        "legacy_ceiling_ms": ceiling,
        "performance_budget_ms": ceiling,
        "within_target_slo": wall_ms <= target,
        "within_target_budget": wall_ms <= ceiling,
    }


def test_tactical_report_coverage_requires_exact_15_plus_20():
    user = {"owned_squad": {"facts": [{"tactical_matchup": {"status": "PARTIAL"}} for _ in range(15)]}}
    watchlist = {
        "positions": {
            "GK": [{"tactical_matchup": {"status": "PARTIAL"}} for _ in range(5)],
            "DEF": [{"tactical_matchup": {"status": "PARTIAL"}} for _ in range(5)],
            "MID": [{"tactical_matchup": {"status": "PARTIAL"}} for _ in range(5)],
            "FWD": [{"tactical_matchup": {"status": "PARTIAL"}} for _ in range(5)],
        }
    }
    assert _tactical_report_coverage(user, watchlist) == {
        "owned": 15,
        "owned_with_tactical": 15,
        "watchlist": 20,
        "watchlist_with_tactical": 20,
    }


def test_selected_profile_runtime_contract_matrix():
    cases = [
        ("fast_decision", 3000.0, True),
        ("fast_decision", 3000.001, False),
        ("live", 5500.0, True),
        ("live", 45000.001, False),
        ("full_refresh", 50000.0, True),
        ("deep_stats", 70000.0, True),
    ]
    for profile, wall_ms, expected in cases:
        passed, detail = _selected_profile_runtime_contract(_runtime(profile, wall_ms))
        assert passed is expected, (profile, wall_ms, detail)


def test_selected_profile_runtime_contract_fails_closed_for_unknown_profile():
    runtime = _runtime("live", 5500.0)
    runtime["execution_profile"] = "unknown"
    passed, detail = _selected_profile_runtime_contract(runtime)
    assert passed is False
    assert detail["reason"] == "UNKNOWN_EXECUTION_PROFILE"


def test_selected_profile_runtime_contract_fails_closed_for_missing_or_malformed_timing():
    missing = _runtime("live", 5500.0)
    missing.pop("total_wall_ms")
    passed, detail = _selected_profile_runtime_contract(missing)
    assert passed is False
    assert detail["reason"] == "MALFORMED_TIMING_TELEMETRY"

    malformed = _runtime("live", 5500.0)
    malformed["total_wall_ms"] = "5500"
    passed, detail = _selected_profile_runtime_contract(malformed)
    assert passed is False
    assert detail["reason"] == "MALFORMED_TIMING_TELEMETRY"


def test_selected_profile_runtime_contract_rejects_runtime_config_mismatch():
    runtime = _runtime("live", 5500.0)
    runtime["target_wall_ms"] = 9999.0
    passed, detail = _selected_profile_runtime_contract(runtime)
    assert passed is False
    assert detail["reason"] == "RUNTIME_SLO_CONFIG_MISMATCH"


def test_selected_profile_runtime_contract_rejects_false_slo_claim():
    runtime = _runtime("live", 12000.0)
    assert runtime["within_target_slo"] is False
    assert runtime["within_target_budget"] is True
    runtime["within_target_slo"] = True
    passed, detail = _selected_profile_runtime_contract(runtime)
    assert passed is False
    assert detail["reason"] == "FALSE_SLO_CLAIM"


def test_definition_of_done_validator_contains_command_pack_requirements():
    text = Path("src/runtime_v3/definition_of_done.py").read_text(encoding="utf-8")
    required = {
        "CI_GREEN",
        "SELECTED_PROFILE_RUNTIME_GREEN",
        "FRESH_RUNTIME_DATA",
        "POST_DEADLINE_OFFICIAL_RECONCILIATION_PROVEN",
        "SCHEDULE_GOVERNANCE_PROVEN",
        "COMPARATOR_CANONICAL",
        "TACTICAL_EVIDENCE_ALL_35",
        "COMPETITIVE_LOAD_EVIDENCE",
        "NO_DUPLICATE_OWNERSHIP",
        "GATE0_16_16",
        "DSS_CORE_50_50",
        "DSS_EXTENSIONS_16_16",
        "ENHANCEMENTS_8_HEALTHY",
        "OWNED_15",
        "WATCHLIST_20_5_PER_POSITION",
        "PRICE_FACT_MODEL_SEPARATED",
        "NO_FABRICATED_EVIDENCE",
        "USER_OVERRIDE_PHASE_AUTHORITY_GOVERNED",
        "OFFICIAL_HISTORY_IMMUTABLE_AUTHORITY",
        "INTERACTIVE_SERVING_UNDER_1S",
        "REPORT_CONTRACTS_GREEN",
        "PRODUCTION_PUBLICATION_SOURCE_COMMIT",
    }
    missing = sorted(item for item in required if item not in text)
    assert not missing, missing
    assert "RUNTIME_FAST_GREEN" not in text
