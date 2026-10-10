from __future__ import annotations

"""Auditable scoring from public, *submitted* Official FPL GW picks.

Do not infer an absent transfer hit as zero. Never promote a provisional
autosub or vice-captain takeover to a finalized Official FPL total.
"""
from typing import Any, Mapping


def integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def score_entry(
    record: Mapping[str, Any],
    live_points: Mapping[int, int],
    *,
    published_standing: Mapping[str, Any] | None = None,
    player_teams: Mapping[int, int] | None = None,
    finished_teams: set[int] | None = None,
    live_minutes: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    picks = list(record.get("picks") or [])
    ids = [integer(row.get("element_id")) for row in picks]
    history = record.get("entry_history")
    history = history if isinstance(history, Mapping) else {}
    substitutions = record.get("automatic_subs")
    chip = str(record.get("active_chip") or "").lower()
    bench_boost = chip in {"bboost", "bench_boost"}
    valid = (
        len(ids) == 15 and len(set(ids)) == 15 and None not in ids
        and all(isinstance(row, Mapping) and integer(row.get("multiplier")) is not None for row in picks)
        and sum(integer(row.get("squad_position")) in range(1, 12) for row in picks) == 11
        and sum(integer(row.get("multiplier")) > 0 for row in picks) == (15 if bench_boost else 11)
        and sum(row.get("captain") is True for row in picks) == 1
        and sum(row.get("vice_captain") is True for row in picks) == 1
    )
    if not valid:
        return {"status": "UNAVAILABLE", "reason": "INVALID_SUBMITTED_PICKS"}
    if not all(i in live_points for i in ids):
        return {"status": "UNAVAILABLE", "reason": "LIVE_PLAYER_POINTS_MISSING"}

    # Official picks can arrive either pre or post automatic substitution.
    # When substitutions have appeared, only apply them if the returned
    # multipliers have NOT yet incorporated their impact.
    factors = {i: integer(p.get("multiplier")) for i, p in zip(ids, picks)}
    official_substitutions = substitutions if isinstance(substitutions, list) else None
    captain = next(p for p in picks if p.get("captain") is True)
    vice = next(p for p in picks if p.get("vice_captain") is True)
    c_id, v_id = captain["element_id"], vice["element_id"]
    captain_subbed_out = False
    subs_applied = 0
    if official_substitutions:
        for substitution in official_substitutions:
            if not isinstance(substitution, Mapping):
                return {"status": "UNAVAILABLE", "reason": "INVALID_OFFICIAL_AUTOSUB"}
            outgoing = integer(substitution.get("element_out"))
            incoming = integer(substitution.get("element_in"))
            if outgoing not in factors or incoming not in factors:
                return {"status": "UNAVAILABLE", "reason": "OFFICIAL_AUTOSUB_NOT_IN_PICKS"}
            if factors[outgoing] > 0 and factors[incoming] == 0:
                # A substituted captain does not transfer the captain bonus
                # to the incoming bench player. Vice captain inherits it.
                factors[incoming] = 1 if outgoing == c_id else factors[outgoing]
                factors[outgoing] = 0
                captain_subbed_out = captain_subbed_out or outgoing == c_id
                subs_applied += 1
            elif factors[outgoing] == 0 and factors[incoming] > 0:
                pass  # Official already updated multipliers.
            else:
                return {"status": "UNAVAILABLE", "reason": "OFFICIAL_AUTOSUB_MULTIPLIER_CONFLICT"}

    # A captain who is confirmed DNP is eventually replaced by VC; do
    # not count an unconfirmed captain replacement as already final.
    teams = player_teams or {}
    minutes = live_minutes or {}
    finished = finished_teams or set()
    c_dnp = teams.get(c_id) in finished and minutes.get(c_id) == 0
    v_appeared = minutes.get(v_id, 0) > 0
    vice_pending = bool(c_dnp and v_appeared and
                        (factors[c_id] > 0 or captain_subbed_out) and
                        factors[v_id] == 1)
    # The official post-processing may already have altered multipliers.
    # In that case, preserve the Official state without a second promotion.
    if vice_pending:
        factors[v_id] = 3 if chip in {"3xc", "triple_captain"} else 2
        factors[c_id] = 0

    # Unfinalized DNP starter: do not pretend a bench substitution is
    # settled while Official has not published an automatic_subs decision.
    pending = False
    if not bench_boost:
        for p in picks:
            pid = p["element_id"]
            if (integer(p.get("squad_position")) or 99) <= 11 and teams.get(pid) in finished and minutes.get(pid) == 0:
                if factors[pid] > 0 and official_substitutions is None:
                    pending = True
                elif factors[pid] > 0 and not official_substitutions:
                    pending = True
    gross = sum(live_points[i] * factors[i] for i in ids)

    hit = integer(history.get("event_transfers_cost"))
    # Entry history is current GW scoped; total_points - points is the
    # published beginning-of-GW baseline, not an authenticated budget.
    history_total = integer(history.get("total_points"))
    history_gw = integer(history.get("points"))
    previous = integer(record.get("previous_overall_points"))
    baseline_source = (
        str(record.get("previous_overall_authority"))
        if previous is not None and record.get("previous_overall_authority")
        else None
    )
    # Historic compatibility diagnostic only: GW-current entry_history may
    # already include hit deductions; difference is not a verified baseline.
    if previous is None and history_total is not None and history_gw is not None:
        previous = history_total - history_gw
        baseline_source = "UNVERIFIED_CURRENT_GW_DIFFERENCE"
    standing = published_standing or {}
    if previous is None:
        standing_total = integer(standing.get("league_total"))
        standing_gw = integer(standing.get("gw_score"))
        if standing_total is not None and standing_gw is not None:
            previous = standing_total - standing_gw
            baseline_source = "OFFICIAL_PUBLISHED_STANDING_DIFFERENCE"
    net = gross - hit if hit is not None else None
    overall = previous + net if previous is not None and net is not None else None
    return {
        "status": "PROVISIONAL" if pending or vice_pending else "CALCULATED",
        "gross_points": gross,
        "hit": hit,
        "net_points": net,
        "previous_overall_points": previous,
        "live_overall_points": overall,
        "baseline_source": baseline_source,
        "baseline_verified": baseline_source in {"OFFICIAL_PREVIOUS_GW_HISTORY", "OFFICIAL_NEW_SEASON_START"},
        "autosub_state": "PENDING" if pending else ("OFFICIAL_APPLIED" if official_substitutions else "NO_OFFICIAL_AUTOSUB"),
        "official_autosub_count": len(official_substitutions) if official_substitutions is not None else None,
        "calculated_autosub_applied": subs_applied,
        "vice_takeover_provisional": vice_pending,
        "multipliers": factors,
        "entry_history_available": bool(history),
        "hit_verified": hit is not None,
    }


def rank_live(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Competition ranks. Equal scores share rank, no invented tie breaker."""
    if not rows or any(integer(row.get("live_overall_points")) is None for row in rows):
        return []
    ordered = sorted(rows, key=lambda r: (-r["live_overall_points"], r["entry_id"]))
    last_score = None
    rank = 0
    for position, row in enumerate(ordered, 1):
        points = row["live_overall_points"]
        if points != last_score:
            rank = position
        row["live_rank"] = rank
        row["tie_unresolved"] = (
            (position > 1 and ordered[position - 2]["live_overall_points"] == points)
            or (position < len(ordered) and ordered[position]["live_overall_points"] == points)
        )
        last_score = points
    return ordered
