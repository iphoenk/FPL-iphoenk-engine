from __future__ import annotations

from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _single_package_map(decision: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for package in decision.get("packages") or []:
        if not isinstance(package, dict) or int(package.get("changes") or 0) != 1:
            continue
        outs = [row for row in package.get("outs") or [] if isinstance(row, dict) and row.get("element") is not None]
        ins = [row for row in package.get("ins") or [] if isinstance(row, dict) and row.get("element") is not None]
        if len(outs) != 1 or len(ins) != 1:
            continue
        out[(int(outs[0]["element"]), int(ins[0]["element"]))] = package
    return out


def _hold_score(decision: dict[str, Any]) -> dict[str, Any]:
    hold = decision.get("hold") if isinstance(decision.get("hold"), dict) else None
    if not hold:
        hold = next((row for row in decision.get("packages") or [] if isinstance(row, dict) and row.get("id") == "HOLD"), None)
    return (hold or {}).get("score") if isinstance((hold or {}).get("score"), dict) else {}


def _canonical_package_context(owned: int, challenger: int, package_map: dict[tuple[int, int], dict[str, Any]], hold_score: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    package = package_map.get((owned, challenger))
    if not package:
        return {"status":"UNVERIFIED","legal":None,"reason":"EXACT_SINGLE_MOVE_NOT_EXPOSED_BY_CANONICAL_PACKAGE_SET","authority":"DECISION_PACKAGE_OPTIMIZER","local_legality_prevalidated":bool(decision.get("local_legality_prevalidated",False))}
    score = package.get("score") if isinstance(package.get("score"), dict) else {}; package_robust=score.get("robust_score"); hold_robust=hold_score.get("robust_score"); net=None
    if package_robust is not None and hold_robust is not None: net=round(_f(package_robust)-_f(hold_robust),3)
    return {"status":"VERIFIED","legal":bool(package.get("legal",True)),"authority":"DECISION_PACKAGE_OPTIMIZER","package_id":package.get("id"),"affordability":package.get("affordability"),"score":score,"hold_robust_score":hold_robust,"package_robust_score":package_robust,"net_transfer_value":net,"net_transfer_value_basis":"canonical_package_robust_score_minus_hold"}


def enrich_with_decision_context(comparator: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    """Attach canonical legality/economics and non-mutating watchlist lifecycle advice."""
    canonical=decision if isinstance(decision,dict) else {}; packages=_single_package_map(canonical); hold=_hold_score(canonical); pairs=[]
    for raw in comparator.get("pairs") or []:
        if not isinstance(raw,dict): continue
        row=dict(raw); owned=int(((row.get("owned") or {}).get("element") or -1)); challenger=int(((row.get("challenger") or {}).get("element") or -1)); package_context=_canonical_package_context(owned,challenger,packages,hold,canonical)
        evidence=dict(row.get("evidence") or {}); evidence["canonical_legality"]="VERIFIED" if package_context.get("status")=="VERIFIED" else "UNVERIFIED"; row["evidence"]=evidence; row["canonical_package_context"]=package_context
        row["transfer_economics"]={"status":package_context.get("status"),"raw_gain_5gw":(((row.get("horizons") or {}).get("5") or {}).get("raw_gain")),"net_transfer_value":package_context.get("net_transfer_value"),"basis":package_context.get("net_transfer_value_basis") or "PENDING_CANONICAL_PACKAGE_EVIDENCE","opportunity_cost":"EMBEDDED_IN_CANONICAL_PACKAGE_SCORE" if package_context.get("status")=="VERIFIED" else "PENDING","structural_cost":"EMBEDDED_IN_CANONICAL_PACKAGE_SCORE" if package_context.get("status")=="VERIFIED" else "PENDING"}
        lane=str(((row.get("challenger") or {}).get("lane") or "")); lifecycle="KEEP"
        if lane=="EMERGING_CHALLENGER" and row.get("classification")=="WATCH_CHALLENGER" and row.get("performance_signal") in {"INTERESTING","STRONG","SUSTAINABLE_CANDIDATE"}:
            row["classification"]="PROMOTE_TO_WATCHLIST"; row["reasons"]=list(row.get("reasons") or [])+["EMERGING_CHALLENGER_EARNS_ADVISORY_WATCHLIST_PROMOTION"]; lifecycle="PROMOTE"
        elif lane=="GOVERNED_WATCHLIST" and row.get("classification")=="HOLD_OWNED":
            lifecycle="REVIEW_DEMOTION"
        elif lane=="GOVERNED_WATCHLIST" and row.get("classification") in {"REVIEW","LEAN_TRANSFER","STRONG_TRANSFER"}:
            lifecycle="RETAIN_PRIORITY"
        row["watchlist_advisory"]={"action":lifecycle,"authority":"ADVISORY_ONLY","mutation":False}; row["watchlist_mutation"]=False; pairs.append(row)
    priority={"STRONG_TRANSFER":6,"LEAN_TRANSFER":5,"REVIEW":4,"PROMOTE_TO_WATCHLIST":3,"WATCH_CHALLENGER":2,"HOLD_OWNED":1}; pairs.sort(key=lambda row:(-priority.get(str(row.get("classification")),0),-_f(((row.get("horizons") or {}).get("5") or {}).get("raw_gain"))))
    counts={}
    for row in pairs:
        label=str(row.get("classification") or "UNKNOWN"); counts[label]=counts.get(label,0)+1
    return {**comparator,"pairs":pairs,"top_comparisons":pairs[:8],"classification_counts":counts,"decision_context":{"status":"AVAILABLE" if canonical else "UNAVAILABLE","authority":"DECISION_SERVICE","exact_single_packages_indexed":len(packages),"no_legality_recomputation":True}}
