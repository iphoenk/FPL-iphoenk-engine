from __future__ import annotations

from typing import Any

from src.utils import DATA, atomic_json, read_json

CHALLENGER = DATA / "owned_challenger_decision_v4.json"
SERVING = DATA / "serving_payload_v4.json"
INTEGRITY = DATA / "publication_integrity_v4.json"


def _assert_complete(payload: dict[str, Any], *, canonical_action: str) -> None:
    completeness = payload.get("official_fact_completeness") or {}
    owned = completeness.get("owned") or {}
    watchlist = completeness.get("watchlist") or {}
    discovery = payload.get("projected_value_market_discovery") or {}
    if payload.get("contract") != "OWNED_CHALLENGER_DECISION_ENGINE_V1":
        raise RuntimeError("owned challenger serving requires canonical contract")
    if payload.get("status") != "READY":
        raise RuntimeError(f"owned challenger serving blocked: status={payload.get('status')}")
    if owned.get("actual") != 15 or owned.get("complete") is not True:
        raise RuntimeError(f"owned challenger serving requires exact 15 owned: {owned}")
    if watchlist.get("actual") != 20 or watchlist.get("complete") is not True:
        raise RuntimeError(f"owned challenger serving requires exact 20 watchlist: {watchlist}")
    if len(payload.get("owned_screening") or []) != 15:
        raise RuntimeError("owned challenger serving requires all-15 screening")
    if payload.get("decision_authority") != "CANONICAL_DECISION_ARBITRATION_V1":
        raise RuntimeError("owned challenger serving requires canonical decision authority")
    if payload.get("overall_decision") != canonical_action:
        raise RuntimeError(
            f"owned challenger canonical action mismatch: challenger={payload.get('overall_decision')} serving={canonical_action}"
        )
    if discovery.get("contract") != "V4_PROJECTED_VALUE_MARKET_DISCOVERY_V1":
        raise RuntimeError("owned challenger serving requires full-universe projected-value discovery contract")
    if discovery.get("full_universe_scanned") is not True:
        raise RuntimeError("owned challenger serving requires full-universe projected-value scan")
    if discovery.get("mandatory_candidate_coverage_complete") is not True:
        raise RuntimeError(
            "owned challenger publication blocked: missing mandatory challenger evaluation "
            f"{discovery.get('missing_mandatory_candidate_ids') or []}"
        )


def compose() -> dict[str, Any]:
    challenger = read_json(CHALLENGER, {})
    serving = read_json(SERVING, {})
    if not serving:
        raise RuntimeError("serving payload missing before challenger composition")
    canonical_action = str(serving.get("overall_action") or "").upper()
    _assert_complete(challenger, canonical_action=canonical_action)

    main_battles = list(challenger.get("main_transfer_battles") or [])
    multi_packages = list(challenger.get("multi_transfer_packages") or [])
    discovery = challenger.get("projected_value_market_discovery") or {}
    serving["owned_challenger_decision"] = {
        "status": challenger.get("status"),
        "challenge_signal": challenger.get("challenge_signal"),
        "overall_decision": canonical_action,
        "decision_authority": challenger.get("decision_authority"),
        "canonical_authority_consistent": True,
        "execution_authorized": challenger.get("execution_authorized"),
        "owned_count": challenger.get("owned_count"),
        "watchlist_count": challenger.get("governed_watchlist_count"),
        "comparison_count": challenger.get("comparison_count"),
        "no_transfer_recommended": challenger.get("no_transfer_recommended"),
        "all15_screening": challenger.get("owned_screening") or [],
        "main_transfer_battles": main_battles,
        "multi_transfer_packages": multi_packages,
        "projected_value_market_discovery": {
            "contract": discovery.get("contract"),
            "full_universe_scanned": discovery.get("full_universe_scanned"),
            "eligible_non_owned_count": discovery.get("eligible_non_owned_count"),
            "mandatory_candidate_ids": discovery.get("mandatory_candidate_ids") or [],
            "evaluated_mandatory_candidate_ids": discovery.get("evaluated_mandatory_candidate_ids") or [],
            "mandatory_candidate_coverage_complete": discovery.get("mandatory_candidate_coverage_complete"),
            "tainted_or_blocked_count": discovery.get("tainted_or_blocked_count"),
            "market_timing_is_not_football_authority": discovery.get("market_timing_is_not_football_authority"),
            "mandatory_review_is_not_automatic_buy": discovery.get("mandatory_review_is_not_automatic_buy"),
        },
        "source": "data/owned_challenger_decision_v4.json",
    }
    serving["main_transfer_battles"] = main_battles
    serving["multi_transfer_packages"] = multi_packages
    serving.setdefault("guardrails", {}).update({
        "owned_challenger_composition_only": True,
        "owned_challenger_exact_15_screened": True,
        "owned_challenger_exact_20_watchlist": True,
        "owned_challenger_reuses_optimization_artifact": True,
        "owned_challenger_reporting_recompute_forbidden": True,
        "owned_challenger_challenge_signal_advisory_only": True,
        "single_canonical_decision_authority": True,
        "full_universe_projected_value_market_scan_required": True,
        "mandatory_challenger_coverage_fail_closed": True,
        "market_urgency_never_auto_buys": True,
    })
    atomic_json(SERVING, serving)

    integrity = read_json(INTEGRITY, {})
    if integrity:
        integrity["owned_challenger"] = {
            "status": "PASS",
            "contract": challenger.get("contract"),
            "owned": 15,
            "watchlist": 20,
            "all15_screened": True,
            "main_transfer_battles_published": True,
            "reporting_recompute": False,
            "challenge_signal": challenger.get("challenge_signal"),
            "canonical_action": canonical_action,
            "canonical_authority_consistent": True,
            "decision_authority": challenger.get("decision_authority"),
            "full_universe_projected_value_market_scan": discovery.get("full_universe_scanned") is True,
            "mandatory_candidate_count": len(discovery.get("mandatory_candidate_ids") or []),
            "mandatory_candidate_coverage_complete": discovery.get("mandatory_candidate_coverage_complete") is True,
            "missing_mandatory_candidate_ids": discovery.get("missing_mandatory_candidate_ids") or [],
            "market_urgency_is_timing_only": True,
        }
        atomic_json(INTEGRITY, integrity)

    return {
        "status": "PASS",
        "owned": 15,
        "watchlist": 20,
        "main_transfer_battles": len(main_battles),
        "multi_transfer_packages": len(multi_packages),
        "mandatory_challengers": len(discovery.get("mandatory_candidate_ids") or []),
        "mandatory_coverage": discovery.get("mandatory_candidate_coverage_complete"),
        "challenge_signal": challenger.get("challenge_signal"),
        "overall_decision": canonical_action,
    }
