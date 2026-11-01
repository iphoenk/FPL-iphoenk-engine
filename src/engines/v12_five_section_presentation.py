"""Mandatory five-section presentation contract for the ordinary ChatGPT report.

Presentation only: canonical DEEP section text is regrouped verbatim under exactly five
top-level sections. Nothing is recalculated, reworded or invented; a missing value stays
missing and a failed check fails closed (the report is then never canonical).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "intelligence" / "v12_five_section_presentation_v1.json"
CANONICAL_IDS = (
    "S01", "S02", "S03", "S04", "S05", "S06", "S06B", "S07", "S08", "S09", "S10", "S11", "S12", "S13",
    "S14", "S14B", "S15", "S15B", "S16", "S16B", "S17", "S18", "S19",
)
OPTIONAL_IDS = frozenset({"S16B"})  # only when the post-match review is due

_SECTION_RE = re.compile(r"(?m)^## (\d{1,2})(B?)\.\s+(.+?)\s*$")
_TOP_RE = re.compile(r"(?m)^## (?!\d)(.+?)\s*$")
_GW_RE = re.compile(r"(?m)^Planning GW:\s*GW?\s*(\d{1,2})\b")
_SLOT_RE = re.compile(r"(?m)^Logical report slot:\s*(\d{1,2} \w{3} \d{4}), (\d{2}:\d{2}) WIB\s*$")
_STATUS_RE = re.compile(r"(?m)^Report:\s*(.+)$")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})(\s)")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def config_failures(cfg: Mapping[str, Any] | None = None) -> list[str]:
    cfg = dict(cfg or load_config())
    groups = cfg.get("section_groups") or {}
    failures = []
    if list(groups) != list(cfg.get("top_level_sections") or []) or len(groups) != 5:
        failures.append("GROUPS_NOT_EXACTLY_FIVE_IN_ORDER")
    flat = [s for ids in groups.values() for s in ids]
    if sorted(flat) != sorted(CANONICAL_IDS):
        failures.append("GROUP_MAP_NOT_EXACT_PARTITION_OF_CANONICAL_SECTIONS")
    return failures


def parse_canonical(body: str) -> dict[str, Any]:
    matches = list(_SECTION_RE.finditer(body))
    sections: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for i, m in enumerate(matches):
        sid = f"S{int(m.group(1)):02d}{m.group(2)}"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if sid in sections:
            sections[sid]["duplicate"] = "1"
            continue
        sections[sid] = {"title": m.group(3), "text": body[m.end():end].strip("\n"), "duplicate": ""}
        order.append(sid)
    header = body[: matches[0].start()] if matches else body
    return {"header": header.rstrip("\n"), "sections": sections, "order": order}


def _names(line: str) -> list[str]:
    return [p.strip() for p in line.split(",") if p.strip()]


def _line(text: str, label: str) -> str | None:
    m = re.search(rf"(?m)^{re.escape(label)}:\s*(.+?)\s*$", text)
    return m.group(1) if m else None


def extract_facts(parsed: Mapping[str, Any]) -> dict[str, Any]:
    secs = parsed["sections"]
    header = parsed["header"]
    s06 = secs.get("S06", {}).get("text", "")
    s08 = secs.get("S08", {}).get("text", "")
    s19 = secs.get("S19", {}).get("text", "")
    s18 = secs.get("S18", {}).get("text", "")
    gw = _GW_RE.search(header)
    slot = _SLOT_RE.search(header)
    xi = _names(_line(s06, "XI") or "")
    bench = _names(_line(s06, "Bench") or "")
    # The renderer words the pair "Current C/VC" when LOCK and "Current C/VC baseline" otherwise
    # (provisional, state shown); both are the canonical pair and are validated identically.
    cv = re.search(r"Current C(?: baseline)?:\s*(.+?);\s*Current VC(?: baseline)?:\s*(.+?);\s*state\s+(\w+)", s08)
    s19_cv = re.search(r"(?m)^Captain(?: baseline)?:\s*(.+?)\s*\(([^)]*)\);\s*Vice(?: baseline)?:\s*(.+?)\.?\s*$", s19)
    s18_cv = re.search(r"(?m)^Canonical C/VC:\s*(.+?)\s*/\s*(.+?);", s18)
    s19_xi_line = _line(s19, "XI") or ""
    s19_xi = _names(s19_xi_line.split(";", 1)[1]) if ";" in s19_xi_line else []
    status = _STATUS_RE.search(header)
    return {
        "gw": int(gw.group(1)) if gw else None,
        "slot_text": f"{slot.group(1)}, {slot.group(2)} WIB" if slot else None,
        "report_status": status.group(1) if status else "",
        "xi": xi,
        "bench": bench,
        "s19_xi": s19_xi,
        "cv_state": {"S08": cv.group(3) if cv else None, "S19": s19_cv.group(2) if s19_cv else None},
        "cv": {"S08": (cv.group(1), cv.group(2)) if cv else None,
               "S19": (s19_cv.group(1), s19_cv.group(3)) if s19_cv else None,
               "S18": (s18_cv.group(1), s18_cv.group(2)) if s18_cv else None},
    }


def _demote(text: str) -> str:
    return _HEADING_RE.sub(lambda m: "#" * min(6, len(m.group(1)) + 1) + m.group(2), text)


def build_view(body: str, cfg: Mapping[str, Any] | None = None) -> str:
    """Regroup the canonical DEEP body under exactly five `## ` sections (verbatim section text)."""
    cfg = dict(cfg or load_config())
    parsed = parse_canonical(body)
    out = [parsed["header"].strip("\n")] if parsed["header"].strip() else []
    for title, ids in cfg["section_groups"].items():
        out += ["", f"## {title}"]
        for sid in sorted((i for i in ids if i in parsed["sections"]), key=CANONICAL_IDS.index):
            sec = parsed["sections"][sid]
            num = sid[1:]
            num = f"{int(num[:2])}{num[2:]}"
            out += ["", f"### {num}. {sec['title']}", _demote(sec["text"])]
    return "\n".join(out).rstrip("\n") + "\n"


def build_degraded_fallback(
    reason: str, cfg: Mapping[str, Any] | None = None,
    *, public_s15b_snapshot: Mapping[str, Any] | None = None,
) -> str:
    """Five sections; optionally include validated public S15B facts, never V12 decisions."""
    cfg = dict(cfg or load_config())
    safe = re.sub(r"\s+", " ", str(reason or "UNSPECIFIED"))[:200]
    out = [f"{cfg['degraded_marker']}: no verified report available ({safe})"]
    for title in cfg["top_level_sections"]:
        out += ["", f"## {title}", "NOT AVAILABLE: no verified canonical data. Nothing was inferred or reused."]
        if title == "MINI-LEAGUE & COMPETITIVE" and public_s15b_snapshot is not None:
            out += ["", render_official_s15b_factual(public_s15b_snapshot)]
    return "\n".join(out) + "\n"


def validate_view(
    view: str,
    *,
    canonical_body: str | None = None,
    expected_gw: int | None = None,
    expected_slot_wib: str | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> list[str]:
    """Deterministic presentation QA. Empty list means pass; any code fails closed."""
    cfg = dict(cfg or load_config())
    failures = config_failures(cfg)
    titles = cfg["top_level_sections"]
    tops = [m.group(1) for m in _TOP_RE.finditer(view)]
    if len(tops) != 5:
        failures.append(f"SECTION_COUNT={len(tops)}")
    if tops != titles:
        failures.append("SECTION_ORDER_OR_TITLE_MISMATCH")
    marker = cfg["degraded_marker"]
    if marker in view:
        # explicit fallback: must carry no report claims
        if re.search(r"(?m)^(XI|Bench|Captain|Current C):", view):
            failures.append("DEGRADED_FALLBACK_CONTAINS_REPORT_CLAIMS")
        return sorted(set(failures))
    if canonical_body is None:
        failures.append("CANONICAL_BODY_REQUIRED")
        return sorted(set(failures))

    parsed = parse_canonical(canonical_body)
    facts = extract_facts(parsed)
    secs = parsed["sections"]
    for sid, sec in secs.items():
        if sec["duplicate"]:
            failures.append(f"CANONICAL_SECTION_DUPLICATE={sid}")
    missing = [s for s in CANONICAL_IDS if s not in secs and s not in OPTIONAL_IDS]
    failures += [f"CANONICAL_SECTION_MISSING={s}" for s in missing]
    unknown = [s for s in secs if s not in CANONICAL_IDS]
    failures += [f"CANONICAL_SECTION_UNKNOWN={s}" for s in unknown]

    # every present canonical section appears exactly once, in its group, in canonical order, verbatim
    expected = build_view(canonical_body, cfg)
    if view.strip() != expected.strip():
        failures.append("VIEW_NOT_VERBATIM_REGROUPING_OF_CANONICAL_BODY")

    if facts["gw"] is None:
        failures.append("GW_MISSING")
    elif expected_gw is not None and facts["gw"] != expected_gw:
        failures.append(f"GW_MISMATCH={facts['gw']}!={expected_gw}")
    if expected_slot_wib is not None and facts["slot_text"] != expected_slot_wib:
        failures.append("OCCURRENCE_SLOT_MISMATCH")

    xi, bench = facts["xi"], facts["bench"]
    if len(xi) != 11:
        failures.append(f"XI_COUNT={len(xi)}")
    if len(set(xi)) != len(xi):
        failures.append("XI_DUPLICATE_PLAYER")
    if len(bench) != 4 or len(set(bench)) != len(bench):
        failures.append(f"BENCH_INVALID={len(bench)}")
    if set(xi) & set(bench):
        failures.append("XI_BENCH_OVERLAP")
    if facts["s19_xi"] and set(facts["s19_xi"]) != set(xi):
        failures.append("XI_INCONSISTENT_S06_S19")

    pairs = {k: v for k, v in facts["cv"].items() if v}
    if not pairs.get("S08"):
        failures.append("CV_MISSING_S08")
    if len(set(pairs.values())) > 1:
        failures.append("CV_INCONSISTENT_ACROSS_SECTIONS")
    states = {v for v in facts["cv_state"].values() if v}
    if len(states) > 1:
        failures.append("CV_STATE_INCONSISTENT")
    for pair in pairs.values():
        cap, vice = pair
        if cap == vice:
            failures.append("CV_SAME_PLAYER")
        if xi and (cap not in xi or vice not in xi):
            failures.append("CV_NOT_IN_XI")

    if "DEGRADED" in facts["report_status"].upper():
        head = "\n".join(view.splitlines()[:8]).upper()
        if "DEGRADED" not in head:
            failures.append("DEGRADED_STATE_NOT_EXPLICIT")
    if "s06-dashboard" in secs.get("S06", {}).get("text", "") and "s06-dashboard" not in view:
        failures.append("PITCH_DASHBOARD_DROPPED")
    return sorted(set(failures))


def gate(body: str, *, expected_gw: int, expected_slot_wib: str) -> list[str]:
    """Convenience for producers: build the view and validate it against the canonical body."""
    try:
        return validate_view(build_view(body), canonical_body=body, expected_gw=expected_gw,
                             expected_slot_wib=expected_slot_wib)
    except Exception as exc:  # fail closed on any parser error
        return [f"PRESENTATION_ERROR={type(exc).__name__}"]


def render_official_s15b_factual(snapshot: Mapping[str, Any]) -> str:
    """Render ONLY published Official FPL league facts, independently of V12.

    Expected inputs are the factual V6 standings_artifact and acquire_manager_picks
    artifacts. This function never fetches owner-private data or upgrades a
    report to canonical. A dashboard copy is not an authority for these fields.
    """
    label = "S15B OFFICIAL FACTUAL ONLY | NOT V12-CANONICAL"
    if not isinstance(snapshot, Mapping):
        return f"{label}\nUNAVAILABLE: official snapshot missing."
    standings = snapshot.get("standings")
    if not isinstance(standings, Mapping) or standings.get("authority") != "OFFICIAL_FPL":
        return f"{label}\nUNAVAILABLE: standings lack Official FPL authority."
    try:
        league_id = int(snapshot["league_id"])
        owner_id = int(snapshot["owner_entry_id"])
        if league_id <= 0 or owner_id <= 0 or int(standings["league_id"]) != league_id:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return f"{label}\nUNAVAILABLE: league/owner identity mismatch."
    raw = standings.get("managers")
    if not isinstance(raw, list) or not raw:
        return f"{label}\nUNAVAILABLE: no official standings rows."
    try:
        rows = {int(row["entry_id"]): row for row in raw if isinstance(row, Mapping)}
    except (ValueError, KeyError, TypeError):
        return f"{label}\nUNAVAILABLE: invalid standings entry."
    if len(rows) != len(raw) or any(entry <= 0 for entry in rows):
        return f"{label}\nUNAVAILABLE: duplicate or invalid league membership."
    transport = snapshot.get("transport", "UNVERIFIED")
    authoritative = transport in {"OFFICIAL_DIRECT", "V6_OFFICIAL_VERIFIED"}
    complete_standings = (authoritative and owner_id in rows and
                          standings.get("complete") is True and
                          standings.get("failed_pages") in ([], None) and
                          standings.get("expected_manager_count") == len(rows))
    user = rows.get(owner_id)
    members = len(rows)
    rank = user.get("league_rank") if user else None
    points = user.get("league_total") if user else None
    if not isinstance(points, int):
        points = None
    scores = [r.get("league_total") for r in rows.values() if isinstance(r.get("league_total"), int)]
    leader = max(scores) if complete_standings and len(scores) == members else None
    gap = leader - points if leader is not None and points is not None else None
    observed = str(standings.get("generated_at") or "UNKNOWN")[:35]
    status = "FULL" if complete_standings else "PARTIAL"
    out = [
        label,
        f"Source transport: {transport} | independent provenance: {'PASS' if authoritative else 'UNVERIFIED'}",
        f"Official FPL league {league_id} | standings {status} | collected {members}"
        + (f"/{members}" if complete_standings else "/UNKNOWN")
        + f" | observed {observed}",
        f"Owner entry {owner_id}: rank {rank if rank is not None else 'UNAVAILABLE'}"
        + f"; points {points if points is not None else 'UNAVAILABLE'}"
        + f"; gap leader {gap if gap is not None else 'UNAVAILABLE'}",
    ]
    # Rank battle is Official standings fact, independent from private P1.8
    # strategy and independent from whether disclosed picks have arrived.
    if user and type(rank) is int and type(points) is int:
        ordered_rivals = sorted(
            (row for row in rows.values()
             if type(row.get("league_rank")) is int
             and type(row.get("league_total")) is int),
            key=lambda row: (row["league_rank"], row["entry_id"]),
        )
        ours_index = next(
            (i for i, row in enumerate(ordered_rivals)
             if row["entry_id"] == owner_id), None,
        )
        if ours_index is not None:
            rivals = ordered_rivals[max(0, ours_index - 3):ours_index] + (
                ordered_rivals[ours_index + 1:ours_index + 4]
            )
            out.extend(["Direct rank neighbours (standings only):",
                        "Rank | Entry | Points | Gap vs OUR",
                        "---:|---:|---:|---:"])
            for rival in rivals:
                diff = rival["league_total"] - points
                out.append(f'{rival["league_rank"]} | {rival["entry_id"]} | '
                           f'{rival["league_total"]} | {diff:+d}')
    picks = snapshot.get("submitted_picks")
    if not isinstance(picks, Mapping) or picks.get("authority") != "OFFICIAL_FPL":
        return "\n".join(out + ["Submitted-picks exposure: UNAVAILABLE (no official picks)."])
    try:
        picks_gw = int(picks["gw"])
        picks_league = int(picks["league_id"])
    except (ValueError, KeyError, TypeError):
        return "\n".join(out + ["Submitted-picks exposure: UNAVAILABLE (GW or league missing)."])
    if picks_league != league_id or picks_gw < 1 or picks.get("deadline_passed") is not True:
        return "\n".join(out + ["Submitted-picks exposure: UNAVAILABLE (league mismatch or deadline not passed)."])
    entries = picks.get("entries")
    if not isinstance(entries, Mapping):
        return "\n".join(out + [f"Submitted picks GW{picks_gw}: UNAVAILABLE (missing entries)."])
    exposure: dict[int, dict[str, int]] = {}
    collected = 0
    invalid = 0
    for entry_id in rows:
        record = entries.get(str(entry_id))
        if not isinstance(record, Mapping) or record.get("status") != "AVAILABLE":
            continue
        submitted = record.get("picks")
        history = record.get("entry_history")
        if (record.get("gw") != picks_gw
            or (isinstance(history, Mapping) and history.get("event") is not None
                and history["event"] != picks_gw)
            or not isinstance(submitted, list) or len(submitted) != 15):
            invalid += 1
            continue
        try:
            ids = [int(p["element_id"]) for p in submitted]
            positions = [int(p["squad_position"]) for p in submitted]
            multipliers = [p["multiplier"] for p in submitted]
            captains = [p["captain"] for p in submitted]
            vice = [p["vice_captain"] for p in submitted]
        except (TypeError, ValueError, KeyError):
            invalid += 1
            continue
        if (len(set(ids)) != 15 or min(ids) < 1 or set(positions) != set(range(1, 16))
            or any(type(m) is not int or m < 0 or m > 3 for m in multipliers)
            or any(type(c) is not bool for c in captains + vice)
            or sum(captains) != 1 or sum(vice) != 1
            or any(c and v for c, v in zip(captains, vice))):
            invalid += 1
            continue
        collected += 1
        for element_id, position, multiplier, captain, vice_captain in zip(
                ids, positions, multipliers, captains, vice):
            v = exposure.setdefault(element_id, {"owned": 0, "starter": 0, "bench": 0,
                                                 "captain": 0, "vice": 0, "multiplier": 0})
            v["owned"] += 1
            v["starter" if position <= 11 else "bench"] += 1
            v["captain"] += int(captain)
            v["vice"] += int(vice_captain)
            v["multiplier"] += multiplier
    full_picks = (complete_standings and collected == members and invalid == 0
                  and picks.get("complete") is True
                  and picks.get("expected_manager_count") == members
                  and set(entries) == {str(k) for k in rows})
    out.append(f"Submitted picks: GW{picks_gw} | {'FULL' if full_picks else 'PARTIAL' if collected else 'UNAVAILABLE'}"
               f" | {collected}/{members} | invalid {invalid} | disclosed previous/current GW only")
    out.append("Never interpret these disclosed picks as still-hidden planning-GW selections.")
    if not collected:
        return "\n".join(out)
    index = snapshot.get("player_index")
    names = index if isinstance(index, Mapping) else {}
    def safe_name(element: int) -> str:
        value = names.get(str(element), names.get(element))
        if isinstance(value, Mapping):
            value = value.get("web_name") or value.get("name")
        text = str(value or f"ID {element}")
        return re.sub(r"[^\w .,'-]", "", text, flags=re.UNICODE)[:44] or f"ID {element}"
    cap = snapshot.get("max_players", 20)
    limit = cap if type(cap) is int and 1 <= cap <= 200 else 20
    out.extend(["Player | Owned | Starter | Bench | Captain | Vice | EO",
                "---|---:|---:|---:|---:|---:|---:"])
    ordered = sorted(exposure.items(), key=lambda pair: (-pair[1]["owned"], pair[0]))
    for player, v in ordered[:limit]:
        den = members if full_picks else collected
        eo = f'{100 * v["multiplier"] / den:.1f}%' if full_picks else "UNAVAILABLE"
        out.append(f'{safe_name(player)} ({player}) | {v["owned"]}/{den}'
                   f' | {v["starter"]}/{den} | {v["bench"]}/{den}'
                   f' | {v["captain"]}/{den} | {v["vice"]}/{den} | {eo}')
    out.append(f"{len(ordered)} unique players in {'complete league' if full_picks else 'collected sample'};"
               f" showing {min(limit, len(ordered))}. EO requires FULL multiplier coverage.")
    return "\n".join(out)



def acquire_public_s15b(
    *, league_id: int = 9477, owner_entry_id: int = 3462711,
    disclosed_gw: int | None = None, transport: str = "auto",
    now: Any = None, client_factory: Any = None,
) -> dict[str, Any]:
    """Direct Official FPL first; proxy fallback cannot certify itself as Official.

    GET-only, public endpoint classes. Does not inspect credentials, FPL my-team,
    canonical V12, OAuth/OIDC, a private repository, or an owner decision.
    """
    from datetime import datetime, timezone
    from src.runtime_v6.domains.report_plane.league_prefetch import build_independent_s15b_snapshot
    from src.runtime_v6.domains.acquisition.official_fpl_client import OfficialFPLClient

    if transport not in {"auto", "official", "dashboard"}:
        raise ValueError("Unsupported public S15B source")
    if type(league_id) is not int or league_id <= 0 or type(owner_entry_id) is not int or owner_entry_id <= 0:
        raise ValueError("Invalid public S15B league/owner identity")
    checked_at = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(checked_at, datetime) or checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("S15B acquisition requires an aware clock")
    modes = ("official", "dashboard") if transport == "auto" else (transport,)
    source_bases = {
        "official": "https://fantasy.premierleague.com/api",
        "dashboard": "https://fpl-iphoenk.vercel.app/api",
    }
    failures = []
    for mode in modes:
        try:
            # public_only prevents even inspecting or rotating OIDC credentials.
            # Only public Official FPL GET endpoint classes are called.
            client = (client_factory(source_bases[mode]) if client_factory is not None
                      else OfficialFPLClient(base_url=source_bases[mode],
                                             timeout_seconds=8.0, retries=1, public_only=True))
            bootstrap = client.bootstrap()
            if bootstrap.get("status") != "LIVE":
                raise ValueError("PUBLIC_BOOTSTRAP_NOT_LIVE")
            data = bootstrap.get("payload")
            if not isinstance(data, Mapping) or not isinstance(data.get("events"), list):
                raise ValueError("PUBLIC_BOOTSTRAP_INVALID")
            disclosed = []
            for event in data["events"]:
                if not isinstance(event, Mapping) or type(event.get("id")) is not int:
                    continue
                try:
                    deadline = datetime.fromisoformat(str(event["deadline_time"]).replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError):
                    continue
                if deadline.tzinfo is not None and deadline <= checked_at:
                    disclosed.append(int(event["id"]))
            if not disclosed:
                raise ValueError("NO_DISCLOSED_GAMEWEEK")
            last_gw = max(disclosed)
            gw = last_gw if disclosed_gw is None else disclosed_gw
            if type(gw) is not int or gw < 1 or gw > last_gw:
                raise ValueError("HIDDEN_OR_INVALID_GAMEWEEK")
            player_index = {
                str(p["id"]): p.get("web_name", f"ID {p['id']}")
                for p in (data.get("elements") or [])
                if isinstance(p, Mapping) and type(p.get("id")) is int
            }
            snap = build_independent_s15b_snapshot(
                client, league_id=league_id, owner_entry_id=owner_entry_id,
                gw=gw, deadline_passed=True, source_transport=(
                    "OFFICIAL_DIRECT" if mode == "official" else "DASHBOARD_PROXY"
                ), player_index=player_index,
            )
            snap["last_disclosed_gw"] = last_gw
            snap["requested_source"] = mode
            snap["official_fetch_failures"] = list(failures)
            return snap
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "HIDDEN_OR_INVALID_GAMEWEEK":
                # A future or invalid requested GW is a hard rejection, not a
                # source outage that the public proxy may circumvent.
                raise
            # Never expose URLs, tokens, upstream bodies or exception details.
            failures.append(f"{mode}: {type(exc).__name__}")
    raise ValueError("PUBLIC_S15B_UNAVAILABLE: " + ", ".join(failures))


def public_s15b_cli(argv: Sequence[str] | None = None) -> int:
    """Independent read-only five-section factual report for ad-hoc verification."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Read-only public Official FPL S15B")
    parser.add_argument("--league-id", type=int, default=9477)
    parser.add_argument("--entry-id", type=int, default=3462711)
    parser.add_argument("--gw", type=int)
    parser.add_argument("--source", choices=("auto", "official", "dashboard"), default="auto")
    parser.add_argument("--max-players", type=int, default=200)
    args = parser.parse_args(argv)
    try:
        snap = acquire_public_s15b(
            league_id=args.league_id, owner_entry_id=args.entry_id,
            disclosed_gw=args.gw, transport=args.source,
        )
        if 1 <= args.max_players <= 200:
            snap["max_players"] = args.max_players
        content = build_degraded_fallback(
            "V12 CANONICAL NOT REQUESTED IN PUBLIC AD-HOC",
            public_s15b_snapshot=snap,
        )
        print(content)
        return 0
    except ValueError as exc:
        print(build_degraded_fallback(str(exc)), file=sys.stdout)
        return 2


if __name__ == "__main__":
    raise SystemExit(public_s15b_cli())
