from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.engines.visible_mode_presentation_locks import load_match_presentation_lock

_MATCH_EVENT_LABELS = {
    "RED_CARD": "Red card",
    "GOAL_RETURN": "Goal",
    "ASSIST_RETURN": "Assist",
    "BENCH_POINTS": "Bench points",
    "DNP_AUTOSUB_PENDING": "DNP / autosub pending",
    "LIVE_APPEARANCE": "Live appearance",
    "NO_MATERIAL_PERSONAL_EVENT": "No material personal event",
}
_STATE_LABELS = {
    "LIVE": "Live",
    "FT": "FT",
    "NOT_STARTED": "Not started",
    "APPEARED": "Appeared",
    "DID_NOT_APPEAR": "Did not appear",
    "PROVISIONAL": "Provisional",
    "FINAL": "Final",
    "AVAILABLE": "Available",
    "UNAVAILABLE": "Unavailable",
    "COMPLETE": "Complete",
    "DEGRADED": "Degraded",
    "PARTIAL": "Partial",
    "PENDING": "Pending",
    "BLOCKED_BY_CAPTAIN_APPEARANCE": "No, captain appeared",
    "PENDING_OFFICIAL_FINALIZATION": "Pending official finalization",
    "LOCKED_SUBMITTED_PICKS": "Submitted FPL picks locked at deadline",
}


def _scalar(value: Any) -> str:
    if value is None or value == "":
        return "UNAVAILABLE"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return "UNAVAILABLE"
    text = str(value)
    upper = text.upper()
    if upper in _STATE_LABELS:
        return _STATE_LABELS[upper]
    if "_" in text and text.upper() == text:
        return text.replace("_", " ").capitalize()
    return text


def _event(value: Any) -> str:
    text = str(value or "")
    return _MATCH_EVENT_LABELS.get(text.upper(), _scalar(text))


def _cell(value: Any) -> str:
    return _scalar(value).replace("|", "/").replace("\n", " ").strip()


def _table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_cell(v) for v in row) + " |"
        for row in rows
    ]
    return [header, divider, *body]


def _population(value: Any, *, denominator: Any = None) -> str:
    if isinstance(value, Mapping):
        numerator = value.get("numerator", value.get("count"))
        denom = value.get("denominator", value.get("total", denominator))
        percent = value.get("percentage", value.get("percent"))
        if numerator is not None and denom not in (None, 0, "0"):
            if percent is None:
                try:
                    percent = 100.0 * float(numerator) / float(denom)
                except (TypeError, ValueError, ZeroDivisionError):
                    percent = None
            if percent is not None:
                return f"{numerator}/{denom} ({float(percent):.1f}%)"
            return f"{numerator}/{denom}"
    if denominator not in (None, 0, "0") and isinstance(value, (int, float)):
        try:
            return f"{value}/{denominator} ({100.0*float(value)/float(denominator):.1f}%)"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return _scalar(value)


def _source_row(label: str, value: Any, default_as_of: Any) -> tuple[str, str, str]:
    if isinstance(value, Mapping):
        return (
            label,
            _scalar(value.get("status") or value.get("state")),
            _scalar(value.get("as_of") or value.get("timestamp") or default_as_of),
        )
    return (label, _scalar(value), _scalar(default_as_of))


def render_match_locked_text(report: Mapping[str, Any]) -> str:
    cfg = load_match_presentation_lock()
    titles = {
        sid: str((cfg.get("sections") or {}).get(sid, {}).get("title") or sid)
        for sid in cfg.get("section_order") or []
    }
    blocks: list[str] = []
    sections = [
        dict(row) for row in report.get("sections") or []
        if isinstance(row, Mapping)
    ]
    for index, section in enumerate(sections, 1):
        sid = str(section.get("section_id") or "").upper()
        title = titles.get(sid, str(section.get("label") or sid))
        state = str(section.get("state") or "")
        content = dict(section.get("content") or {}) if isinstance(section.get("content"), Mapping) else {}
        lines = [f"## MATCH {index} — {title}", f"Status: {_scalar(state)}"]
        reason = str(section.get("degradation_reason") or "").strip()
        if state.upper() != "COMPLETE" and reason:
            lines.append("Scope note: " + _scalar(reason))

        if sid == "MATCH1":
            live = content.get("fixtures_live")
            ft = content.get("fixtures_ft")
            ns = content.get("fixtures_not_started")
            lines.extend([
                f"Scoring GW: {_scalar(content.get('scoring_gw'))}",
                f"Fixtures live: {_scalar(live)}",
                f"Fixtures FT: {_scalar(ft)}",
                f"Fixtures not started: {_scalar(ns)}",
                f"As of: {_scalar(content.get('timestamp'))}",
                f"Lifecycle / current phase: {_scalar(content.get('lifecycle_mode'))}",
                (
                    f"{_scalar(live)} pertandingan sedang berjalan, "
                    f"{_scalar(ft)} selesai, {_scalar(ns)} belum mulai."
                ),
                "Weather: MATCH CURRENT",
            ])
        elif sid == "MATCH2":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            lines.extend(_table(
                ("Player","Pos","Club","Match status"),
                [(
                    r.get("name") or r.get("player"),
                    r.get("position"),
                    r.get("club") or r.get("team"),
                    _scalar(r.get("fixture_status") or r.get("match_status")),
                ) for r in rows],
            ))
            lines.extend([
                "",
                "Starting XI",
                ", ".join(str(x) for x in content.get("xi") or []) or "UNAVAILABLE",
                "",
                "Bench",
                ", ".join(str(x) for x in content.get("bench") or []) or "UNAVAILABLE",
                "",
                "Scoring authority",
                "Submitted FPL picks locked at deadline.",
            ])
        elif sid == "MATCH3":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            material=[r for r in rows if r.get("player") or r.get("name")]
            if material:
                lines.extend(_table(
                    ("Player","Event","Match status","Minutes","Raw pts","Multiplier","Effective pts"),
                    [(
                        r.get("player") or r.get("name"),
                        _event(r.get("personal_state") or r.get("event")),
                        _scalar(r.get("fixture_status") or r.get("match_status")),
                        r.get("minutes"), r.get("raw_points"), r.get("multiplier"), r.get("effective_points"),
                    ) for r in material],
                ))
            else:
                lines.append("Belum ada event pemain kita yang mengubah scoring consequence.")
        elif sid == "MATCH4":
            bench_gk=content.get("bench_gk")
            if isinstance(bench_gk, Mapping):
                bench_gk=bench_gk.get("name") or bench_gk.get("player")
            priority=[
                (r.get("name") or r.get("player")) if isinstance(r, Mapping) else r
                for r in content.get("outfield_autosub_priority") or []
            ]
            bench_rows=[("GK",bench_gk)]
            bench_rows.extend((str(i), value) for i,value in enumerate(priority[:3],1))
            while len(bench_rows)<4:
                bench_rows.append((str(len(bench_rows)), "UNAVAILABLE"))
            lines.extend([
                "Bench GK: " + _scalar(bench_gk),
                "Outfield autosub priority: " + (
                    ", ".join(f"{i} {_scalar(value)}" for i, value in enumerate(priority[:3], 1))
                    if priority else "UNAVAILABLE"
                ),
            ])
            lines.extend(_table(("Slot","Player"),bench_rows[:4]))
            outs=list(content.get("potential_out") or [])
            ins=list(content.get("bench_candidates") or [])
            lines.extend([
                "",
                f"Current autosub state: {_scalar(content.get('status'))}",
                "Potential player out: " + (", ".join(str(x) for x in outs) if outs else "None proven"),
                "Potential replacement: " + (", ".join(str(x) for x in ins) if ins else "None proven"),
                "Official finalization pending: " + ("No" if content.get("official_finalization_authoritative") and not outs else "Yes"),
            ])
            pairings=[dict(r) for r in content.get("autosub_pairings") or [] if isinstance(r, Mapping)]
            if pairings:
                lines.append("")
                lines.extend(_table(
                    ("Out","Potential in","Status"),
                    [(r.get("out"),r.get("potential_in"),_scalar(r.get("status"))) for r in pairings],
                ))
        elif sid == "MATCH5":
            cap=dict(content.get("captain") or {})
            vice=dict(content.get("vice") or {})
            lines.extend(_table(
                ("Role","Player","Raw pts","Multiplier","Effective pts","Appearance"),
                [
                    ("Captain",cap.get("name"),cap.get("raw_points"),cap.get("multiplier"),cap.get("effective_points"),_scalar(cap.get("appearance_state"))),
                    ("Vice",vice.get("name"),vice.get("raw_points"),vice.get("multiplier"),vice.get("effective_points"),_scalar(vice.get("appearance_state"))),
                ],
            ))
            lines.extend([
                f"Vice takeover: {_scalar(content.get('vice_takeover_state'))}",
                f"Final consequence: {_scalar(content.get('final_consequence'))}",
            ])
        elif sid == "MATCH6":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            lines.extend(_table(
                ("Player","Match status","Minutes","Raw pts","Multiplier","Effective pts"),
                [(
                    r.get("player"), _scalar(r.get("state") or r.get("match_status")),
                    r.get("minutes"),r.get("raw_points"),r.get("multiplier"),r.get("effective_points"),
                ) for r in rows],
            ))
        elif sid == "MATCH7":
            status=_scalar(content.get("status") or ("PROVISIONAL" if content.get("provisional") is True else "FINAL"))
            lines.extend([
                f"Status: {status}",
                "BPS can still change while a match is live." if status=="Provisional" else "Bonus/BPS is final for the supported fixtures.",
            ])
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            if rows:
                lines.extend(_table(("Player","Bonus","BPS"),[(r.get("player"),r.get("bonus"),r.get("bps")) for r in rows]))
            else:
                lines.append("None yet.")
        elif sid == "MATCH8":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            if rows:
                lines.extend(_table(
                    ("Player","Event","Detail","Match status","Decision implication"),
                    [(
                        r.get("player") or r.get("name"), _event(r.get("event") or r.get("type")),
                        r.get("detail") or r.get("description"), _scalar(r.get("match_status") or r.get("fixture_status")),
                        _scalar(r.get("decision_implication") or r.get("implication")),
                    ) for r in rows],
                ))
            else:
                lines.append("No material structured event yet.")
            lines.append("Observation does not automatically change the model until governed recomputation occurs.")
        elif sid == "MATCH9":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            if rows:
                lines.extend(_table(
                    ("Player","Club","Signal","Evidence","Sustainable / noisy","OUR15 / next-opponent implication"),
                    [(
                        r.get("player") or r.get("name"),r.get("club") or r.get("team"),r.get("signal"),
                        r.get("evidence"),_scalar(r.get("sustainable_noisy") or r.get("sustainability")),
                        _scalar(r.get("our15_next_opponent_implication") or r.get("implication")),
                    ) for r in rows],
                ))
            else:
                lines.append("No material league-wide signal yet.")
        elif sid == "MATCH10":
            submitted=dict(content.get("submitted_picks_exposure") or {})
            standings=dict(content.get("live_standings_rank") or {})
            expected=submitted.get("expected_count",content.get("expected_manager_count"))
            available=submitted.get("available_count",content.get("collected_manager_count"))
            summary=dict(content.get("user_summary") or {})
            lines.extend([
                f"League: {_scalar(content.get('league_name') or content.get('league') or 'ICON+')}",
                f"Coverage: {_scalar(available)}/{_scalar(expected)}" if available is not None and expected is not None else "Coverage: UNAVAILABLE",
                f"Evidence state: exposure {_scalar(submitted.get('state') or state)}; standings {_scalar(standings.get('state'))}",
                f"Current live rank: {_scalar(content.get('current_live_rank') or summary.get('rank'))}",
                f"Current live points: {_scalar(content.get('current_live_points') or summary.get('live_points') or summary.get('total'))}",
            ])
            exposure=[dict(r) for r in (content.get("material_player_exposure") or content.get("exposure_rows") or []) if isinstance(r, Mapping)]
            if exposure:
                lines.append("")
                lines.extend(_table(
                    ("Player","Owned","Starter","Captain","Vice","EO","Live consequence"),
                    [(
                        r.get("player"), _population(r.get("owned"),denominator=r.get("denominator",expected)),
                        _population(r.get("starter"),denominator=r.get("denominator",expected)),
                        _population(r.get("captain"),denominator=r.get("denominator",expected)),
                        _population(r.get("vice"),denominator=r.get("denominator",expected)),
                        _population(r.get("eo"),denominator=r.get("denominator",expected)),
                        _scalar(r.get("live_consequence")),
                    ) for r in exposure],
                ))
            else:
                lines.append("Detailed player exposure unavailable; healthy submitted-picks coverage is retained above.")
            rivals=[dict(r) for r in (content.get("direct_rival_live_consequence") or (content.get("rival_live_points") or {}).get("rows") or []) if isinstance(r, Mapping)]
            if rivals:
                lines.append("")
                lines.extend(_table(
                    ("Manager","Live points","Gap","Captain","Key threat","Key shield"),
                    [(
                        r.get("manager") or r.get("manager_name"),r.get("live_points"),r.get("gap"),
                        r.get("captain"),r.get("key_threat"),r.get("key_shield"),
                    ) for r in rivals],
                ))
        elif sid == "MATCH11":
            rows=[dict(r) for r in content.get("rows") or [] if isinstance(r, Mapping)]
            if rows:
                lines.extend(_table(
                    ("Player / Team","Learning","Evidence","Next-GW implication","Action state"),
                    [(
                        r.get("player_team") or r.get("player") or r.get("team"),r.get("learning"),r.get("evidence"),
                        r.get("next_gw_implication") or r.get("implication"),_scalar(r.get("action_state") or "Watch"),
                    ) for r in rows],
                ))
            else:
                lines.append("No governed next-GW learning row yet.")
            lines.append("Evidence is not an automatic transfer.")
        elif sid == "MATCH12":
            lines.extend([
                "Next critical observation",
                _scalar(content.get("observation") or content.get("next_critical_observation")),
                "",
                "Why it matters",
                _scalar(content.get("why_it_matters")),
                "",
                "When to reassess",
                _scalar(content.get("when_to_reassess")),
            ])
        elif sid == "MATCH13":
            default_as_of=content.get("generated_at")
            rows=[
                _source_row("Official FPL event-live",content.get("event_live"),default_as_of),
                _source_row("Submitted picks",content.get("submitted_picks"),default_as_of),
                _source_row("Prediction snapshot",content.get("prediction_snapshot"),default_as_of),
                _source_row("Mini-league submitted picks",content.get("mini_league_submitted_picks"),default_as_of),
                _source_row("Live standings",content.get("live_standings"),default_as_of),
                _source_row("Match evidence feed",content.get("match_evidence_feed"),default_as_of),
            ]
            lines.extend(_table(("Source","Status","As of"),rows))
            lines.extend([
                "FACT: Official FPL event-live and submitted picks.",
                "MODEL: Frozen prediction snapshot where available.",
                "INFERENCE: Personal and league consequences are presentation-layer interpretation of governed evidence.",
            ])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).rstrip()+"\n"


def deadline_header_lines(report: Mapping[str, Any]) -> list[str]:
    p=dict(report.get("deadline_presentation") or {})
    mode=str(report.get("report_mode") or "DEADLINE").upper()
    return [
        f"FPL MASTER V12 — {mode} REPORT",
        f"Official deadline: {_scalar(p.get('official_deadline'))}",
        f"Countdown: {_scalar(p.get('countdown'))}",
        f"Checkpoint: {_scalar(p.get('checkpoint'))}",
        f"Decision state: {_scalar(p.get('decision_state'))}",
    ]


def deadline_section_overlay_lines(section_id: str, report: Mapping[str, Any]) -> list[str]:
    p=dict(report.get("deadline_presentation") or {})
    block=dict(p.get(section_id) or {})
    if not block:
        return []
    lines: list[str]=[]
    if section_id=="S01":
        lines.extend([
            "### Deadline state",
            f"Countdown: {_scalar(p.get('countdown'))}",
            f"Transfer legality: {_scalar(block.get('transfer_legality'))}",
            f"Execution readiness: {_scalar(block.get('execution_readiness'))}",
            f"Unresolved blocker: {_scalar(block.get('unresolved_blocker'))}",
        ])
    elif section_id=="S03":
        lines.extend([
            "### Deadline decision delta",
            f"Change since previous deadline checkpoint: {_scalar(block.get('change_since_previous_checkpoint'))}",
            f"What changed: {_scalar(block.get('what_changed'))}",
            f"What did not change: {_scalar(block.get('what_did_not_change'))}",
            f"Does this change WAIT / PREPARE / ACT: {_scalar(block.get('decision_change'))}",
        ])
    elif section_id=="S05":
        news=[dict(r) for r in block.get("late_news_rows") or [] if isinstance(r, Mapping)]
        if news:
            lines.append("### Latest actionable team news")
            lines.extend(_table(
                ("Player","News","Availability impact","Evidence tier","As of","Decision impact"),
                [(
                    r.get("player"),r.get("news"),r.get("availability_impact"),_scalar(r.get("evidence_tier")),
                    r.get("as_of"),_scalar(r.get("decision_impact")),
                ) for r in news],
            ))
        xi=[dict(r) for r in block.get("predicted_xi_rows") or [] if isinstance(r, Mapping)]
        if xi:
            lines.append("### Predicted XI / leak tier")
            lines.extend(_table(
                ("Player","Predicted status","Evidence tier","Confidence","Decision consequence"),
                [(
                    r.get("player"),_scalar(r.get("predicted_status")),_scalar(r.get("evidence_tier")),
                    _scalar(r.get("confidence")),_scalar(r.get("decision_consequence")),
                ) for r in xi],
            ))
    elif section_id=="S08":
        rows=[dict(r) for r in block.get("captain_rows") or [] if isinstance(r, Mapping)]
        if rows:
            lines.append("### Deadline captain status")
            lines.extend(_table(
                ("Role","Player","State","Reversal trigger"),
                [(r.get("role"),r.get("player"),_scalar(r.get("state")),r.get("reversal_trigger")) for r in rows],
            ))
    elif section_id=="S14":
        rows=[dict(r) for r in block.get("route_rows") or [] if isinstance(r, Mapping)]
        if rows:
            lines.append("### Deadline route table")
            lines.extend(_table(
                ("Route","Legal","Affordable","1GW","3GW","5GW","P>HOLD","Value of waiting","Reversal / Abort","Action"),
                [(
                    r.get("route"),_scalar(r.get("legal")),_scalar(r.get("affordable")),r.get("1gw"),r.get("3gw"),r.get("5gw"),
                    r.get("p_hold"),r.get("value_of_waiting"),r.get("reversal_abort"),_scalar(r.get("action")),
                ) for r in rows],
            ))
    elif section_id=="S18":
        action=dict(block.get("action_board") or block)
        fields=["NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL","BEST ALTERNATIVE"]
        lines.append("### Deadline Action Board")
        lines.extend(_table(("Field","Current call"),[(field,action.get(field)) for field in fields]))
    return lines


def render_gw_lock_package(content: Mapping[str, Any]) -> list[str]:
    mapping=[
        ("Target GW","target_gw"),("Transfers out","transfers_out"),("Transfers in","transfers_in"),
        ("Number of moves","number_of_moves"),("FT / hit treatment","ft_hit_treatment"),("Bank after","bank_after_if_known"),
        ("Formation","formation"),("Exact XI (11)","xi_exact11"),("Bench GK","bench_gk"),
        ("Outfield bench priority 1-3","outfield_bench_priority_1_3"),("Captain","captain"),("Vice-captain","vice_captain"),
        ("Chip","chip"),("Primary action","primary_action"),("Abort trigger","abort_trigger"),("Fallback","fallback"),
        ("Evidence timestamp","evidence_timestamp"),("Canonical authority version","canonical_authority_version"),
    ]
    def display(label: str, value: Any) -> str:
        if label=="Bank after" and value in (None,""):
            return "UNKNOWN / UNAVAILABLE"
        if isinstance(value, Mapping):
            return "UNAVAILABLE"
        if isinstance(value, Sequence) and not isinstance(value,(str,bytes)):
            return ", ".join(str(x) for x in value) if value else "None"
        return _scalar(value)
    return _table(("Field","Value"),[(label,display(label,content.get(key))) for label,key in mapping])
