from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

MIN_OWNERSHIP_PCT = 0.5
MIN_ABS_NET = 5_000
HIGH_NET = 25_000


def classify(net_transfers: int, ownership_pct: float, estimated_owners: int) -> dict:
    ratio = net_transfers / max(estimated_owners, 1)
    actionable = ownership_pct >= MIN_OWNERSHIP_PCT and abs(net_transfers) >= MIN_ABS_NET
    confidence = "HIGH" if actionable and abs(net_transfers) >= HIGH_NET else "MEDIUM" if actionable else "NOISE"
    return {
        "momentum": ratio,
        "actionable": actionable,
        "confidence": confidence,
        "market_noise": not actionable,
        "min_ownership_pct": MIN_OWNERSHIP_PCT,
        "min_abs_net": MIN_ABS_NET,
    }


def classify_row(row: dict) -> dict:
    own = float(row.get("ownership_pct") or 0.0)
    net = int(row.get("net_transfers") or 0)
    # Engine-persisted rows already contain the ratio, but estimated owners can be
    # reconstructed well enough for classification without relying on it.
    meta = classify(net, own, 1)
    return {**row, "actionable": meta["actionable"], "confidence": meta["confidence"], "market_noise": meta["market_noise"]}


def filtered_pressure(rows: Iterable[dict], direction: str, limit: int = 25) -> tuple[list[dict], list[dict]]:
    classified = [classify_row(r) for r in rows]
    actionable = [r for r in classified if r["actionable"]]
    noise = [r for r in classified if not r["actionable"]]
    if direction == "buy":
        actionable.sort(key=lambda r: (float(r.get("momentum") or 0), abs(int(r.get("net_transfers") or 0))), reverse=True)
    else:
        actionable.sort(key=lambda r: (float(r.get("momentum") or 0), -abs(int(r.get("net_transfers") or 0))))
    noise.sort(key=lambda r: abs(int(r.get("net_transfers") or 0)), reverse=True)
    return actionable[:limit], noise[:limit]


def apply_to_payload(prices: dict) -> dict:
    buys, buy_noise = filtered_pressure(prices.get("top_buy_pressure", []), "buy")
    sells, sell_noise = filtered_pressure(prices.get("top_sell_pressure", []), "sell")
    return {
        **prices,
        "filter_policy": {
            "min_ownership_pct": MIN_OWNERSHIP_PCT,
            "min_abs_net_transfers": MIN_ABS_NET,
            "purpose": "suppress tiny-denominator momentum noise; ratio alone is never actionable",
        },
        "top_buy_pressure": buys,
        "top_sell_pressure": sells,
        "market_noise": {"buy": buy_noise, "sell": sell_noise},
    }


def patch_files(data_dir: str | Path = "data") -> None:
    root = Path(data_dir)
    prices_path = root / "prices.json"
    latest_path = root / "latest.json"
    prices = json.loads(prices_path.read_text(encoding="utf-8"))
    filtered = apply_to_payload(prices)
    prices_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest["price_summary"] = {
            "confirmed_changes": filtered.get("confirmed_changes", []),
            "top_buy_pressure": filtered.get("top_buy_pressure", [])[:10],
            "top_sell_pressure": filtered.get("top_sell_pressure", [])[:10],
            "filter_policy": filtered.get("filter_policy", {}),
            "market_noise_count": {
                "buy": len(filtered.get("market_noise", {}).get("buy", [])),
                "sell": len(filtered.get("market_noise", {}).get("sell", [])),
            },
        }
        latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_files()
