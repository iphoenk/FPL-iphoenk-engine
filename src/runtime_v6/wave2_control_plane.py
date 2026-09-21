from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .report_contract import ReportContractError, classify_report_outcome, safety_net_decision

WAVE2_REPORT_MODES = (
    "normal_hourly",
    "04:30_deep",
    "05:30_price",
    "12:30_deep",
    "21:30_deep",
    "match_mode",
    "deadline_mode",
    "ad_hoc_deep",
)

WAVE2_FAILURE_MAPPINGS = (
    "provider_amber",
    "auth_unavailable",
    "auth_expired",
    "stale_predictor",
    "duplicate_prefetch",
    "delayed_execution",
    "corrupt_candidate",
)


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReportContractError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReportContractError("timestamp must include timezone offset")
    return parsed.astimezone(timezone.utc)


def report_slot_key(report_kind: str, logical_slot: str) -> str:
    kind = str(report_kind or "").strip()
    if not kind:
        raise ReportContractError("report_kind is required")
    slot = _parse_time(logical_slot)
    return f"{kind}|{slot.isoformat()}"


def advance_report_slot_ledger(
    previous: dict[str, Any] | None,
    *,
    report_kind: str,
    logical_slot: str,
    observed_at: str,
    owner: str,
    prefetched: bool = False,
    delivered: bool = False,
    report_contract_pass: bool = False,
    delivery_proof_valid: bool = False,
    maximum_slots: int = 96,
) -> dict[str, Any]:
    """Persist report-slot ownership without allowing a second owner to steal a slot.

    The ledger is deliberately independent from core scheduler proof. It can be used by
    the primary report path and Safety Net to deduplicate a logical report checkpoint.
    """
    key = report_slot_key(report_kind, logical_slot)
    observed = _parse_time(observed_at).isoformat()
    owner = str(owner or "").strip()
    if not owner:
        raise ReportContractError("report slot owner is required")

    state = dict(previous or {})
    rows = [dict(row) for row in state.get("slots") or [] if isinstance(row, dict)]
    by_key = {str(row.get("slot_key")): row for row in rows if row.get("slot_key")}
    row = dict(by_key.get(key) or {})
    existing_owner = str(row.get("owner") or "").strip()
    ownership_conflict = bool(existing_owner and existing_owner != owner)

    if not row:
        row = {
            "slot_key": key,
            "report_kind": report_kind,
            "logical_slot": _parse_time(logical_slot).isoformat(),
            "owner": owner,
            "owned_at": observed,
            "prefetched": False,
            "delivered": False,
            "report_contract_pass": False,
            "delivery_proof_valid": False,
            "report_slot_fulfilled": False,
            "duplicate_attempts": 0,
        }
    elif ownership_conflict:
        row["duplicate_attempts"] = int(row.get("duplicate_attempts") or 0) + 1
        row["last_duplicate_owner"] = owner
        row["last_duplicate_attempt_at"] = observed
    else:
        row["duplicate_attempts"] = int(row.get("duplicate_attempts") or 0) + 1
        row["last_duplicate_owner"] = owner
        row["last_duplicate_attempt_at"] = observed

    if not ownership_conflict:
        if prefetched:
            row["prefetched"] = True
            row["prefetched_at"] = observed
        if delivered:
            row["delivered"] = True
            row["delivered_at"] = observed
        if report_contract_pass:
            row["report_contract_pass"] = True
        if delivery_proof_valid:
            row["delivery_proof_valid"] = True

    outcome = classify_report_outcome(
        data_slot_fulfilled=False,
        report_contract_pass=row.get("report_contract_pass") is True,
        visible_emitted=row.get("delivered") is True,
        delivery_proof_valid=row.get("delivery_proof_valid") is True,
    )
    row["report_slot_fulfilled"] = outcome["REPORT_SLOT_FULFILLED"]
    row["state"] = (
        "FULFILLED" if row.get("report_slot_fulfilled") is True
        else "DELIVERED_UNFULFILLED" if row.get("delivered") is True
        else "PREFETCHED" if row.get("prefetched") is True
        else "OWNED"
    )
    row["ownership_conflict"] = ownership_conflict
    by_key[key] = row

    ordered = sorted(by_key.values(), key=lambda item: str(item.get("logical_slot") or ""))
    ordered = ordered[-max(1, int(maximum_slots)):]
    return {
        "schema_version": 1,
        "generated_at": observed,
        "slots": ordered,
        "summary": {
            "tracked_report_slots": len(ordered),
            "prefetched_slots": sum(item.get("prefetched") is True for item in ordered),
            "delivered_slots": sum(item.get("delivered") is True for item in ordered),
            "fulfilled_report_slots": sum(item.get("report_slot_fulfilled") is True for item in ordered),
            "ownership_conflicts": sum(item.get("ownership_conflict") is True for item in ordered),
        },
        "governance": {
            "core_scheduler_proof_independent": True,
            "first_owner_wins": True,
            "safety_net_must_dedupe_only_fulfilled_slots": True,
            "prefetch_and_raw_delivery_are_nonterminal": True,
        },
    }


def safety_net_from_ledger(
    ledger: dict[str, Any] | None,
    *,
    report_kind: str,
    logical_slot: str,
    primary_owner: str = "FPL_MASTER_MONITOR",
) -> dict[str, Any]:
    key = report_slot_key(report_kind, logical_slot)
    row = next(
        (
            item
            for item in (ledger or {}).get("slots") or []
            if isinstance(item, dict) and item.get("slot_key") == key
        ),
        {},
    )
    decision = safety_net_decision(
        logical_slot=logical_slot,
        primary_owned=str(row.get("owner") or "") == primary_owner,
        prefetched=row.get("prefetched") is True,
        delivered=row.get("delivered") is True,
        report_contract_pass=row.get("report_contract_pass") is True,
        delivery_proof_valid=row.get("delivery_proof_valid") is True,
        report_slot_fulfilled=row.get("report_slot_fulfilled") is True,
    )
    return {**decision, "report_kind": report_kind, "slot_key": key, "slot_state": row.get("state")}


def control_plane_state_from_ledger(
    ledger: dict[str, Any] | None,
    *,
    observed_at: str,
    cadence_minutes: int = 60,
) -> dict[str, Any]:
    """Expose Wave 2 time concepts without fabricating scheduler proof from payload age."""
    payload = dict(ledger or {})
    rows = [
        dict(row)
        for row in payload.get("slots") or []
        if isinstance(row, dict)
        and row.get("fulfilled") is True
        and row.get("fulfilled_by") == "CHATGPT"
    ]
    rows.sort(key=lambda row: str(row.get("slot") or ""))
    latest = rows[-1] if rows else {}
    logical_slot = latest.get("slot")
    scheduler_cycle = latest.get("observed_at")
    current = _parse_time(observed_at)

    age_seconds = None
    next_expected = None
    if scheduler_cycle:
        age_seconds = max(0.0, (current - _parse_time(str(scheduler_cycle))).total_seconds())
    if logical_slot:
        next_expected = (_parse_time(str(logical_slot)) + timedelta(minutes=max(1, int(cadence_minutes)))).isoformat()

    auxiliary = [
        dict(row)
        for row in payload.get("auxiliary_operational_slots") or []
        if isinstance(row, dict) and row.get("observed_at")
    ]
    operational_times = [str(row.get("observed_at")) for row in rows + auxiliary if row.get("observed_at")]
    last_operational = max(operational_times, key=lambda value: _parse_time(value)) if operational_times else None

    return {
        "observed_at": current.isoformat(),
        "logical_slot": logical_slot,
        "last_chatgpt_scheduler_cycle_at": scheduler_cycle,
        "last_authoritative_cycle_at": scheduler_cycle,
        "last_operational_cycle_at": last_operational,
        "last_processed_logical_slot": logical_slot,
        "next_expected_logical_slot": next_expected,
        "scheduler_proof_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "run_provenance": {
            "run_id": latest.get("run_id"),
            "schedule_kind": latest.get("schedule_kind"),
            "slot_key": latest.get("core_slot_key"),
            "publication_generation_id": latest.get("publication_generation_id"),
        },
        "governance": {
            "prefetch_cannot_advance_scheduler_proof": True,
            "payload_freshness_cannot_advance_scheduler_proof": True,
            "authoritative_transport": "FPL_MASTER_SLOT",
        },
    }


def price_checkpoint_contract(
    *,
    official_price_fact_count: int,
    predictor: dict[str, Any] | None,
    mini_league_status: str,
    target_frontier_available: bool,
    auth_requested: bool,
) -> dict[str, Any]:
    """Evaluate 05:30 readiness while preserving official predictor vs confirmed-fact semantics."""
    model = dict(predictor or {})
    provenance_label = str(model.get("provenance_label") or model.get("semantic_class") or "UNAVAILABLE")
    predictor_available = bool(model) and str(model.get("availability") or "").upper() in {"AVAILABLE", "PARTIAL"}
    official_status = str(model.get("predictor_official_status") or "").upper()
    product_evidence = model.get("independent_official_product_evidence") is True
    official_claim_forbidden = bool(
        official_status.startswith("VERIFIED_OFFICIAL")
        and not product_evidence
    )
    reasons: list[str] = []
    if int(official_price_fact_count) <= 0:
        reasons.append("OFFICIAL_PRICE_FACTS_MISSING")
    if not predictor_available:
        reasons.append("PREDICTOR_UNAVAILABLE")
    if official_claim_forbidden:
        reasons.append("PREDICTOR_OFFICIAL_STATUS_UNVERIFIED")
    if str(mini_league_status).upper() not in {"AVAILABLE", "PARTIAL"}:
        reasons.append("ICON_EXPOSURE_UNAVAILABLE")
    if not target_frontier_available:
        reasons.append("TARGET_FRONTIER_UNAVAILABLE")

    status = "PASS" if not reasons else "PARTIAL"
    return {
        "status": status,
        "official_price_facts": "AVAILABLE" if official_price_fact_count > 0 else "UNAVAILABLE",
        "official_price_fact_count": int(official_price_fact_count),
        "predictor": "AVAILABLE" if predictor_available else "UNAVAILABLE",
        "predictor_provenance": provenance_label,
        "predictor_may_be_called_official": bool(
            product_evidence and official_status.startswith("VERIFIED_OFFICIAL")
        ),
        "mini_league_exposure": str(mini_league_status).upper(),
        "target_frontier": "AVAILABLE" if target_frontier_available else "UNAVAILABLE",
        "auth": "REQUESTED" if auth_requested else "NOT REQUESTED",
        "reasons": reasons,
        "report_delivery_required_even_if_partial": True,
    }
