from __future__ import annotations

from src.sources.official_price_predictor import build_market_context
from src.utils import DATA, atomic_json, iso_now, read_json

RUNTIME = DATA / "runtime"
SNAPSHOT = RUNTIME / "snapshot.v1.json"


def _watchlist_ids(predictions: dict, owned_ids: set[int], limit: int = 20) -> list[int]:
    rows = predictions.get("players") or []
    out: list[int] = []
    for row in rows:
        element = int(row.get("element") or 0)
        if element <= 0 or element in owned_ids or element in out:
            continue
        out.append(element)
        if len(out) >= limit:
            break
    return out


def _pressure(rows: list[dict], total_players: int) -> tuple[list[dict], list[dict]]:
    enriched = []
    for row in rows:
        ownership = float(row.get("ownership_pct") or 0.0)
        owners = max(1, int(total_players * ownership / 100.0))
        net = int(row.get("transfers_in_event") or 0) - int(row.get("transfers_out_event") or 0)
        enriched.append({
            **row,
            "net_transfers": net,
            "momentum": net / owners,
        })
    buys = sorted(enriched, key=lambda row: (row["momentum"], row["net_transfers"]), reverse=True)[:25]
    sells = sorted(enriched, key=lambda row: (row["momentum"], row["net_transfers"]))[:25]
    return buys, sells


def _natural_action(row: dict, *, owned: bool) -> str:
    direction = row.get("direction")
    urgency = row.get("model_urgency")
    if row.get("evidence_state") == "UNAVAILABLE":
        return "Data prediksi harga resmi belum tersedia."
    if row.get("official_calibrating"):
        return "Prediktor resmi masih dikalibrasi; jangan percepat keputusan karena harga."
    if row.get("official_locked_until"):
        return "Perubahan harga terkunci sampai waktu yang tercatat; tidak ada alasan mengejar harga sebelum lock berakhir."
    if urgency in {"HIGH", "CRITICAL"} and direction == "RISE":
        return "Prediksi resmi mengarah kuat ke kenaikan pada pembaruan berikutnya; cek kelayakan transfer dan ruang anggaran."
    if urgency in {"HIGH", "CRITICAL"} and direction == "FALL":
        return "Prediksi resmi mengarah kuat ke penurunan; cek dampak sell value dan fleksibilitas anggaran."
    if urgency == "WATCH":
        return "Ada tekanan harga yang perlu dipantau, tetapi belum cukup untuk memaksa transfer."
    return "Belum ada tekanan harga yang cukup untuk mempercepat transfer." if owned else "Harga dipantau sebagai konteks, bukan alasan membeli."


def _compact_radar(rows: list[dict], owned_ids: set[int]) -> list[dict]:
    out = []
    for row in rows:
        projections = {int(item["offset"]): item for item in row.get("official_projections") or [] if item.get("offset") is not None}
        out.append({
            "element": row.get("element"),
            "name": row.get("name"),
            "official_price": row.get("now_cost"),
            "ownership_pct": row.get("ownership_pct"),
            "current_progress": row.get("current_official_progress"),
            "offset0_projection": (projections.get(0) or {}).get("projected_percent"),
            "offset1_projection": (projections.get(1) or {}).get("projected_percent"),
            "offset2_projection": (projections.get(2) or {}).get("projected_percent"),
            "raw_likelihood": row.get("official_likelihood_raw"),
            "direction": row.get("direction"),
            "next_update_wib": row.get("next_official_price_update_wib"),
            "eta_seconds": row.get("eta_seconds"),
            "possible_future_cycle": row.get("predicted_change_cycle"),
            "model_urgency": row.get("model_urgency"),
            "freshness": row.get("freshness"),
            "source": row.get("source"),
            "action": _natural_action(row, owned=int(row.get("element") or 0) in owned_ids),
        })
    return out


def refresh_price_context() -> dict:
    raw = read_json(SNAPSHOT, {})
    team = read_json(DATA / "team.json", {})
    predictions = read_json(DATA / "predictions_v4.json", {})
    latest = read_json(DATA / "latest.json", {})
    bootstrap = ((raw.get("official") or {}).get("bootstrap") or {})
    if not bootstrap.get("elements"):
        raise RuntimeError("Official bootstrap required for V4 price context")

    owned_ids = {int(row.get("element") or 0) for row in team.get("squad") or [] if row.get("element") is not None}
    watchlist_ids = _watchlist_ids(predictions, owned_ids)
    previous_cache = read_json(DATA / "price_cache.json", {})
    context = build_market_context(
        bootstrap,
        observed_at=raw.get("generated_at"),
        now=iso_now(),
        previous_cache=previous_cache,
        owned_ids=owned_ids,
        watchlist_ids=watchlist_ids,
    )
    buys, sells = _pressure(context["players"], int(bootstrap.get("total_players") or 0))
    context["top_buy_pressure"] = buys
    context["top_sell_pressure"] = sells
    context["all15_actionable_price_radar"] = _compact_radar(context.get("all15") or [], owned_ids)
    context["all20_external_dss_watchlist"] = _compact_radar(context.get("all20_watchlist") or [], owned_ids)
    context["market_context_role"] = "TIMING_AFFORDABILITY_OPTIONALITY_ONLY"
    context["football_decision_authority"] = "SUBORDINATE"

    atomic_json(DATA / "price_cache.json", context.pop("price_cache"))
    atomic_json(DATA / "prices.json", context)

    next_update = next((row.get("next_official_price_update_wib") for row in context.get("players") or [] if row.get("next_official_price_update_wib")), None)
    latest["price_summary"] = {
        "health": context.get("health"),
        "confirmed_changes": context.get("confirmed_changes") or [],
        "next_official_price_update_wib": next_update,
        "all15": context.get("all15_actionable_price_radar") or [],
        "all20": context.get("all20_external_dss_watchlist") or [],
        "summary": "Harga resmi dipakai untuk timing, affordability, optionality, dan perlindungan sell value; bukan sebagai alasan mandiri untuk BUY/SELL/HIT.",
    }
    latest.setdefault("market_context", {})["price"] = {
        "status": (context.get("health") or {}).get("status"),
        "source": context.get("source"),
        "contract": context.get("contract"),
        "policy_id": context.get("policy_id"),
        "next_official_price_update_wib": next_update,
    }
    latest.setdefault("files", {})["price_context"] = "data/prices.json"
    latest.setdefault("meta", {})["official_price_predictor_runtime_wired"] = True
    latest["meta"]["price_predictor_no_network_refetch"] = True
    latest["meta"]["price_signal_subordinate_to_football"] = True
    atomic_json(DATA / "latest.json", latest)
    return context


if __name__ == "__main__":
    result = refresh_price_context()
    print({
        "service": "v4_price_context",
        "health": (result.get("health") or {}).get("status"),
        "players": len(result.get("players") or []),
        "all15": len(result.get("all15_actionable_price_radar") or []),
        "all20": len(result.get("all20_external_dss_watchlist") or []),
    })
