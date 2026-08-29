from pathlib import Path

from src.runtime_v3.definition_of_done import _tactical_report_coverage


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


def test_definition_of_done_validator_contains_command_pack_requirements():
    text = Path("src/runtime_v3/definition_of_done.py").read_text(encoding="utf-8")
    required = {
        "CI_GREEN",
        "RUNTIME_FAST_GREEN",
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
