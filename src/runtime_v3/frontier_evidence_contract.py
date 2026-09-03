from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Any

import numpy as np

from src.rules import SQUAD_RULES
from src.utils import DATA, read_json

HORIZONS = (3, 5, 10, 15)
MAX_CLUB = int(SQUAD_RULES.get("max_players_per_club") or 3)
DIMENSIONS = [
    "net_xpts3", "net_xpts5", "net_xpts10", "net_xpts15", "changes", "objective_std",
    "xmins_uncertainty_minutes_std_sum", "tactical_role_uncertainty_missing_dimensions",
    "price_risk_adverse_progress_percent", "resulting_itb", "club_slot_headroom",
    "roster_change_uncertainty_players",
]
MAXIMIZE_IDX = np.asarray((0, 1, 2, 3, 9, 10), dtype=np.intp)
MINIMIZE_IDX = np.asarray((4, 5, 6, 7, 8, 11), dtype=np.intp)
EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def _evidence() -> tuple[dict[int, dict[str, Any]], list[int], dict[int, dict[str, Any]]]:
    projections = read_json(DATA / "projections.json", {}) or {}
    players = {int(row.get("element") or -1): row for row in projections.get("players") or []}
    team = read_json(DATA / "team.json", {}) or {}
    owned = [int(row.get("element") or -1) for row in team.get("team_value_ledger") or [] if int(row.get("element") or -1) > 0]
    prices = read_json(DATA / "prices.json", {}) or {}
    price = {int(row.get("element_id") or row.get("element") or -1): row for row in prices.get("players") or []}
    return players, owned, price


def _squad_ids(package: dict[str, Any]) -> list[int]:
    _, owned, _ = _evidence()
    outs = {int(row.get("element") or -1) for row in package.get("outs") or []}
    ins = [int(row.get("element") or -1) for row in package.get("ins") or []]
    return [element for element in owned if element not in outs] + ins


def _tactical_missing(player: dict[str, Any]) -> int:
    dimensions = ((player.get("tactical_matchup") or {}).get("evidence_dimensions") or {})
    return sum(1 for state in dimensions.values() if state != "AVAILABLE")


def _roster_uncertain(player: dict[str, Any]) -> int:
    adaptation = (((player.get("historical_prior") or {}).get("transfer_adaptation")) or {})
    uncertain = bool(adaptation) and adaptation.get("state") != "SAME_CLUB" and bool(adaptation.get("confidence_ceiling") or adaptation.get("old_role_prior_retired") is False)
    return int(uncertain)


def _adverse_price(row: dict[str, Any], outgoing: bool) -> float:
    direction = str(row.get("direction") or "")
    adverse = (outgoing and direction == "RISE") or ((not outgoing) and direction == "FALL")
    if not adverse:
        return 0.0
    return max(abs(_f(row.get("projection_offset_0_percent"))), abs(_f(row.get("current_progress_percent"))))


def metrics(package: dict[str, Any], hold_horizons: dict[str, Any]) -> tuple[float, ...]:
    horizons = (package.get("score") or {}).get("horizons") or {}
    players, _, price = _evidence()
    squad = [players.get(element, {}) for element in _squad_ids(package)]
    clubs = Counter(int(player.get("team_id") or -1) for player in squad if int(player.get("team_id") or -1) > 0)
    club_headroom = sum(max(0, MAX_CLUB - count) for count in clubs.values())
    price_risk = sum(_adverse_price(price.get(int(row.get("element") or -1), {}), True) for row in package.get("outs") or [])
    price_risk += sum(_adverse_price(price.get(int(row.get("element") or -1), {}), False) for row in package.get("ins") or [])
    return tuple(_f((horizons.get(str(h)) or {}).get("mean")) - _f((hold_horizons.get(str(h)) or {}).get("mean")) for h in HORIZONS) + (
        int(package.get("changes") or 0),
        _f((package.get("score") or {}).get("objective_std"), 1e9),
        sum(_f((player.get("xmins") or {}).get("minutes_std")) for player in squad),
        sum(_tactical_missing(player) for player in squad),
        price_risk,
        float((package.get("affordability") or {}).get("resulting_itb") or 0),
        float(club_headroom),
        sum(_roster_uncertain(player) for player in squad),
    )


def dominates(left: tuple[float, ...], right: tuple[float, ...], eps: float = EPS) -> bool:
    no_worse = all(left[index] >= right[index] - eps for index in MAXIMIZE_IDX) and all(left[index] <= right[index] + eps for index in MINIMIZE_IDX)
    strict = any(left[index] > right[index] + eps for index in MAXIMIZE_IDX) or any(left[index] < right[index] - eps for index in MINIMIZE_IDX)
    return no_worse and strict


def _row(metric: tuple[float, ...], package: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": package.get("id"), "changes": package.get("changes"), "robust_score": (package.get("score") or {}).get("robust_score"),
        "net_xpts": {str(h): metric[index] for index, h in enumerate(HORIZONS)}, "objective_std": metric[5],
        "xmins_uncertainty_minutes_std_sum": round(metric[6], 3),
        "tactical_role_uncertainty_missing_dimensions": int(metric[7]),
        "price_risk_adverse_progress_percent": round(metric[8], 3),
        "structural_flexibility": {"resulting_itb": int(metric[9]), "club_slot_headroom": int(metric[10])},
        "roster_change_uncertainty_players": int(metric[11]),
    }


class Frontier:
    def __init__(self, hold_horizons: dict[str, Any]) -> None:
        self.hold_horizons = hold_horizons
        self.rows: list[tuple[tuple[float, ...], dict[str, Any]]] = []
        self._matrix = np.empty((0, len(DIMENSIONS)), dtype=np.float64)

    @classmethod
    def from_hold(cls, hold: dict[str, Any]) -> "Frontier":
        return cls(((hold.get("score") or {}).get("horizons") or {}))

    def add(self, package: dict[str, Any]) -> None:
        metric = metrics(package, self.hold_horizons)
        target = np.asarray(metric, dtype=np.float64)
        if self._matrix.shape[0]:
            existing = self._matrix
            existing_no_worse = (
                np.all(existing[:, MAXIMIZE_IDX] >= target[MAXIMIZE_IDX] - EPS, axis=1)
                & np.all(existing[:, MINIMIZE_IDX] <= target[MINIMIZE_IDX] + EPS, axis=1)
            )
            existing_strict = (
                np.any(existing[:, MAXIMIZE_IDX] > target[MAXIMIZE_IDX] + EPS, axis=1)
                | np.any(existing[:, MINIMIZE_IDX] < target[MINIMIZE_IDX] - EPS, axis=1)
            )
            if np.any(existing_no_worse & existing_strict):
                return

            target_no_worse = (
                np.all(target[MAXIMIZE_IDX] >= existing[:, MAXIMIZE_IDX] - EPS, axis=1)
                & np.all(target[MINIMIZE_IDX] <= existing[:, MINIMIZE_IDX] + EPS, axis=1)
            )
            target_strict = (
                np.any(target[MAXIMIZE_IDX] > existing[:, MAXIMIZE_IDX] + EPS, axis=1)
                | np.any(target[MINIMIZE_IDX] < existing[:, MINIMIZE_IDX] - EPS, axis=1)
            )
            keep = ~(target_no_worse & target_strict)
            if not np.all(keep):
                self.rows = [row for row, retain in zip(self.rows, keep.tolist()) if retain]
                self._matrix = existing[keep]

        self.rows.append((metric, package))
        self._matrix = np.concatenate((self._matrix, target.reshape(1, -1)), axis=0)

    def output(self, limit: int, evaluated: int) -> dict[str, Any]:
        rows = [_row(metric, package) for metric, package in self.rows]
        rows.sort(key=lambda row: (_f(row.get("robust_score")), str(row.get("id") or "")), reverse=True)
        return {
            "count": len(rows), "packages": rows[:max(1, int(limit))], "authority": "REPRESENTATION_ONLY",
            "dimensions_used": DIMENSIONS, "dimensions_pending_richer_runtime_evidence": [],
            "dimension_semantics": {
                "maximize": ["net_xpts3", "net_xpts5", "net_xpts10", "net_xpts15", "resulting_itb", "club_slot_headroom"],
                "minimize": ["changes", "objective_std", "xmins_uncertainty_minutes_std_sum", "tactical_role_uncertainty_missing_dimensions", "price_risk_adverse_progress_percent", "roster_change_uncertainty_players"],
            },
            "price_risk_source": "OFFICIAL_PRICE_PREDICTOR_RAW_PROGRESS_WHEN_AVAILABLE_ZERO_WHEN_NO_ADVERSE_SIGNAL",
            "tactical_role_uncertainty_source": "COUNT_NON_AVAILABLE_GOVERNED_EVIDENCE_DIMENSIONS_NO_ARBITRARY_WEIGHT",
            "structural_flexibility_source": "OFFICIAL_ITB_AND_FPL_CLUB_SLOT_HEADROOM",
            "roster_uncertainty_source": "GOVERNED_NEW_SIGNING_TRANSFER_ADAPTATION",
            "never_second_scoring_authority": True, "search_authority": "FULL",
            "representation_input": "ALL_EVALUATED_LEGAL_PACKAGES", "evaluated_legal_package_count": evaluated,
        }


def skyline_indices(values: Any, *, eps: float = EPS):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != len(DIMENSIONS):
        raise ValueError(f"skyline metrics must have shape (n, {len(DIMENSIONS)})")
    n = array.shape[0]
    if n <= 1:
        return np.arange(n, dtype=np.int32)
    dominated_mask = np.zeros(n, dtype=bool)
    block = 256
    for start in range(0, n, block):
        stop = min(n, start + block)
        target = array[start:stop]
        for source_start in range(0, n, block):
            source = array[source_start:min(n, source_start + block)]
            no_worse = np.all(source[:, None, MAXIMIZE_IDX] >= target[None, :, MAXIMIZE_IDX] - eps, axis=2) & np.all(source[:, None, MINIMIZE_IDX] <= target[None, :, MINIMIZE_IDX] + eps, axis=2)
            strict = np.any(source[:, None, MAXIMIZE_IDX] > target[None, :, MAXIMIZE_IDX] + eps, axis=2) | np.any(source[:, None, MINIMIZE_IDX] < target[None, :, MINIMIZE_IDX] - eps, axis=2)
            dominated_mask[start:stop] |= np.any(no_worse & strict, axis=0)
            if np.all(dominated_mask[start:stop]):
                break
    return np.flatnonzero(~dominated_mask).astype(np.int32)


def install() -> None:
    from src.engines import package_optimizer_exhaustive_accelerated as accelerated
    from src.engines import package_optimizer_exhaustive_finalize as base
    base._metrics = metrics
    base._dominates = dominates
    base._Frontier = Frontier
    accelerated.exact_skyline_indices = skyline_indices
