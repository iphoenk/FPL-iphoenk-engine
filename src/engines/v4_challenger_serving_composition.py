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


def compose() -> dict[str, Any]:
    challenger = read_json(CHALLENGER, {})
    serving = read_json(SERVING, {})
    if not serving:
        raise RuntimeError("serving payload missing before challenger composition")
    canonical_action = str(serving.get("overall_action") or "").upper()
    _assert_complete(challenger, canonical_action=canonical_action)

    main_battles = list(challenger.get("main_transfer_battles") or [])
    multi_packages = list(challenger.get("multi_transfer_packages") or [])
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
        }
        atomic_json(INTEGRITY, integrity)

    return {
        "status": "PASS",
        "owned": 15,
        "watchlist": 20,
        "main_transfer_battles": len(main_battles),
        "multi_transfer_packages": len(multi_packages),
        "challenge_signal": challenger.get("challenge_signal"),
        "overall_decision": canonical_action,
    }
