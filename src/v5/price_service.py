from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from src.engines import price_radar as canonical


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / max(1, denominator), 4)


def _observed_at(value: datetime | str | None, fallback: datetime) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = canonical._parse_dt(value)
    if parsed is None:
        return fallback, True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, False


def _confirmed_changes(raw_rows: list[dict[str, Any]], previous_state: dict[str, Any]) -> list[dict[str, Any]]:
    previous = (previous_state or {}).get("players") if isinstance((previous_state or {}).get("players"), dict) else {}
    confirmed: list[dict[str, Any]] = []
    for raw in raw_rows:
        element = canonical._int(raw.get("id"))
        current = canonical._int(raw.get("now_cost"))
        if element is None or current is None:
            continue
        prior = previous.get(str(element)) if isinstance(previous, dict) else None
        old = canonical._int((prior or {}).get("now_cost")) if isinstance(prior, dict) else None
        if old is None or old == current:
            continue
        confirmed.append(
            {
                "element": element,
                "name": raw.get("web_name"),
                "previous": old,
                "current": current,
                "delta": current - old,
                "state": "CONFIRMED_PRICE_CHANGE",
            }
        )
    return confirmed


def build_transfer_momentum_evidence(
    bootstrap: dict[str, Any],
    price_rows: list[dict[str, Any]],
    *,
    minimum_coverage_ratio: float = 0.95,
) -> dict[str, Any]:
    """Verify transfer-momentum evidence without treating it as predictor authority."""
    elements = [
        row
        for row in bootstrap.get("elements") or []
        if isinstance(row, dict) and row.get("id") is not None
    ]
    prices = {
        int(row["element"]): row
        for row in price_rows
        if isinstance(row, dict) and row.get("element") is not None
    }
    covered = linked = price_matches = active = total_in = total_out = 0
    for player in elements:
        eid = int(player["id"])
        has_counts = player.get("transfers_in_event") is not None and player.get("transfers_out_event") is not None
        if has_counts:
            covered += 1
            tin = int(player.get("transfers_in_event") or 0)
            tout = int(player.get("transfers_out_event") or 0)
            total_in += tin
            total_out += tout
            if tin != tout:
                active += 1
        price = prices.get(eid)
        if isinstance(price, dict):
            linked += 1
            if (
                price.get("now_cost") is not None
                and player.get("now_cost") is not None
                and int(price["now_cost"]) == int(player["now_cost"])
            ):
                price_matches += 1
    n = len(elements)
    count_ratio = _ratio(covered, n)
    linkage_ratio = _ratio(linked, n)
    price_match_ratio = _ratio(price_matches, n)
    available = bool(n) and min(count_ratio, linkage_ratio, price_match_ratio) >= float(minimum_coverage_ratio)
    return {
        "evidence_state": "AVAILABLE" if available else "INSUFFICIENT",
        "players": n,
        "transfer_count_covered": covered,
        "transfer_count_coverage_ratio": count_ratio,
        "price_snapshot_linked": linked,
        "price_snapshot_linkage_ratio": linkage_ratio,
        "current_price_matches": price_matches,
        "current_price_match_ratio": price_match_ratio,
        "players_with_nonzero_net_momentum": active,
        "total_transfers_in_event": total_in,
        "total_transfers_out_event": total_out,
        "net_transfers_event": total_in - total_out,
        "source": "Official FPL bootstrap transfer counts + governed Official price snapshot",
        "supporting_market_evidence_only": True,
        "predictor_direction_inferred_from_transfers": False,
        "external_threshold_invented": False,
        "predicted_price_change_invented": False,
        "coverage_threshold_is_data_contract_only": True,
    }


def _market_pressure(rows: list[dict[str, Any]], total_players: int, *, descending: bool) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ownership = canonical._float(row.get("ownership_percent"))
        net_in = canonical._int(row.get("transfers_in_event"))
        net_out = canonical._int(row.get("transfers_out_event"))
        if ownership is None or net_in is None or net_out is None:
            continue
        estimated_owners = max(1, int(total_players * ownership / 100.0))
        net = net_in - net_out
        enriched.append(
            {
                **row,
                "estimated_owners": estimated_owners,
                "net_transfers": net,
                "momentum": net / estimated_owners,
            }
        )
    enriched.sort(
        key=lambda row: (float(row.get("momentum") or 0.0), abs(int(row.get("net_transfers") or 0))),
        reverse=descending,
    )
    return enriched[: canonical.PRICE_PRESSURE_LIST_SIZE]


def build_price_snapshot(
    bootstrap: dict[str, Any],
    *,
    previous_state: dict[str, Any] | None = None,
    owned_ids: Iterable[int] = (),
    now: datetime | None = None,
    observed_at: datetime | str | None = None,
    transport_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build governed V5 market context from the shared V3/V4 Official provider.

    No independent predictor parsing lives in V5. Price evidence can affect timing,
    affordability and optionality, but it is not football decision authority.
    """
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    observed, observed_assumed = _observed_at(observed_at, generated_at)
    raw_rows = [row for row in bootstrap.get("elements") or [] if isinstance(row, dict)]
    raw_hash = canonical._raw_payload_hash(raw_rows)
    positions = canonical._position_map(bootstrap.get("element_types") or [])
    confirmed = _confirmed_changes(raw_rows, previous_state or {})
    confirmed_by_id = {int(row["element"]): row for row in confirmed}

    normalised = [
        canonical._normalise_player(
            raw,
            position_by_type=positions,
            observed_at=observed,
            now=generated_at,
            raw_payload_hash=raw_hash,
            confirmed_change=confirmed_by_id.get(canonical._int(raw.get("id")) or -1),
        )
        for raw in raw_rows
    ]
    enriched, trajectory_state = canonical.build_trajectory(normalised, previous_state or {}, generated_at)
    health = canonical._overall_health(enriched, transport_health or {"status": "SNAPSHOT_DERIVED"})
    health["observed_at_assumed_from_build_time"] = observed_assumed
    health["canonical_provider"] = "src.engines.price_radar"
    health["canonical_policy"] = "config/intelligence/price_radar.json"
    if health.get("status") == "FAIL":
        raise RuntimeError(f"Official FPL predictor schema unusable: {health}")

    owned = {int(value) for value in owned_ids}
    by_id = {
        int(row["element_id"]): row
        for row in enriched
        if row.get("element_id") is not None
    }
    all15 = [
        canonical._served_evidence(by_id[element], owned=True)
        for element in sorted(owned)
        if element in by_id
    ]
    ranked = sorted(enriched, key=canonical._risk_sort, reverse=True)
    market_watch = [
        canonical._served_evidence(row, owned=False)
        for row in ranked
        if int(row.get("element_id") or -1) not in owned
    ][: canonical.MAX_MARKET_WATCH]
    alert_rows = [
        canonical._served_evidence(row, owned=int(row.get("element_id") or -1) in owned)
        for row in ranked
        if str(row.get("model_urgency")) in canonical.ALERT_LEVELS
    ]
    rising = [row for row in ranked if row.get("direction") == "RISE"][: canonical.PRICE_PRESSURE_LIST_SIZE]
    falling = [row for row in ranked if row.get("direction") == "FALL"][: canonical.PRICE_PRESSURE_LIST_SIZE]
    total_players = int(bootstrap.get("total_players") or 0)
    buys = _market_pressure(enriched, total_players, descending=True)
    sells = _market_pressure(enriched, total_players, descending=False)
    contract = canonical.canonical_contract()
    transfer_momentum = build_transfer_momentum_evidence(bootstrap, enriched)
    next_update = next(
        (row.get("next_official_price_update_at") for row in enriched if row.get("next_official_price_update_at")),
        None,
    )

    prices = {
        "schema_version": int(contract["schema_version"]),
        "generated_at": generated_at.isoformat(),
        "source": "OFFICIAL_FPL",
        "authority_rank": list(contract["source_authority"]),
        "health": health,
        "contract": contract,
        "raw_payload_hash": raw_hash,
        "confirmed_changes": confirmed,
        "players": enriched,
        "top_buy_pressure": buys,
        "top_sell_pressure": sells,
        "top_rise_risk": rising,
        "top_fall_risk": falling,
        "all15_actionable_price_radar": all15,
        "all15_coverage": {"expected": len(owned), "resolved": len(all15), "complete": len(all15) == len(owned)},
        "market_watch_candidates": market_watch,
        "next_official_price_update_at": next_update,
        "governance": {
            "shared_v3_v4_v5_provider": "src.engines.price_radar",
            "official_bootstrap_is_primary_authority": True,
            "authenticated_session_required": False,
            "ui_scraping": False,
            "dedicated_predictor_endpoint": False,
            "current_and_projected_progress_separate": True,
            "raw_likelihood_preserved_without_unverified_mapping": True,
            "null_never_coerced_to_zero": True,
            "no_intra_cycle_crossing_eta": True,
            "price_signal_subordinate_to_football_decision": True,
            "exact_all20_is_bound_after_governed_watchlist_selection": True,
        },
    }
    return {
        "status": health.get("status"),
        "contract": contract,
        "prices": prices,
        "trajectory_state": {**trajectory_state, "contract": "official_price_predictor_state_v3", "raw_payload_hash": raw_hash},
        "alerts": {
            "generated_at": generated_at.isoformat(),
            "health": health,
            "alerts": alert_rows,
            "owned_price_radar": all15,
            "owned_price_radar_count": len(all15),
            "market_watch_candidates": market_watch,
        },
        "transfer_momentum": transfer_momentum,
    }
