from __future__ import annotations
from collections import Counter
from collections.abc import Iterable
from src.engines.fpl_rules_2026 import LEGAL_FORMATIONS, MAX_PER_CLUB, POSITION_COUNTS, SQUAD_SIZE


def formation_from_rows(rows: Iterable[dict]) -> str | None:
    rows = list(rows)
    counts = {p: sum(row.get("position") == p for row in rows) for p in ("DEF", "MID", "FWD")}
    formation = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return formation if formation in LEGAL_FORMATIONS else None


def squad_shape_is_legal(players: Iterable[dict]) -> bool:
    rows = list(players)
    if len(rows) != SQUAD_SIZE:
        return False
    position_counts = Counter(str(row.get("position") or "") for row in rows)
    if any(position_counts.get(position, 0) != expected for position, expected in POSITION_COUNTS.items()):
        return False
    clubs = Counter(row.get("team_id", row.get("team")) for row in rows)
    return bool(clubs) and max(clubs.values(), default=0) <= MAX_PER_CLUB


def plan_legality_checks(plan: dict, compliance: dict | None = None) -> dict[str, tuple[bool, str]]:
    xi = list(plan.get("starting_xi") or [])
    xi_ids = {int(row.get("element")) for row in xi if row.get("element") is not None}
    captain = int((plan.get("captain") or {}).get("element") or -1)
    vice = int((plan.get("vice_captain") or {}).get("element") or -1)
    bench = plan.get("bench") or {}
    chip = plan.get("chip_context") or {}
    formation = formation_from_rows(xi)
    declared = plan.get("formation")
    return {
        "G0-10": (len(xi) == 11 and formation is not None and declared == formation, f"formation={declared},derived={formation},xi={len(xi)}"),
        "G0-11": (sum(row.get("position") == "GK" for row in xi) == 1, "starting GK"),
        "G0-12": (captain in xi_ids and vice in xi_ids and captain != vice, f"captain={captain},vice={vice}"),
        "G0-13": (bool(bench.get("gk")) and len(bench.get("order") or []) == 3, "bench structure"),
        "G0-14": (chip.get("single_chip_rule_respected") is True and (not compliance or compliance.get("overall") == "PASS"), f"single_chip={chip.get('single_chip_rule_respected')},rules={(compliance or {}).get('overall')}"),
    }
