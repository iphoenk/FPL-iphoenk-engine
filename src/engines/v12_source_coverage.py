"""Fail-closed source coverage contract for deadline-day V12 reports.

This module validates evidence actually collected by upstream adapters. It does
not pretend to fetch sources; missing or inaccessible providers stay explicit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

REQUIRED_SOURCE_CATEGORIES = (
    "OFFICIAL_PL_FPL",
    "OFFICIAL_CLUBS",
    "OFFICIAL_SOCIAL",
    "BEAT_REPORTERS_NEWS",
    "INDEPENDENT_ANALYTICS",
    "FPL_COMMUNITY",
    "USER_SUPPLIED_LEADS",
)
REQUIRED_DECISION_DOMAINS = (
    "PLAYER_MINUTES",
    "STARTING_XI_FORMATION",
    "CAPTAIN_VICE",
    "TRANSFER_HOLD_HITS",
    "COMPETITIVE_WINDOW",
)
VALID_RESULTS = {
    "CHECKED_WITH_FINDINGS", "CHECKED_NO_CHANGE", "INACCESSIBLE", "NOT_CHECKED"
}


def _parse_time(value: Any) -> datetime | None:
    try:
        token = str(value or "").strip()
        if not token:
            return None
        return datetime.fromisoformat(token.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def validate_news_source_coverage(
    coverage: Mapping[str, Any] | None,
    *,
    require_full: bool = True,
) -> dict[str, Any]:
    """Validate source attempts, freshness, all 20 clubs and auditable URLs."""
    data = dict(coverage or {})
    failures: list[str] = []
    scan_at = _parse_time(data.get("scan_at"))
    deadline = _parse_time(data.get("deadline"))
    if scan_at is None:
        failures.append("SOURCE_SCAN_TIMESTAMP_MISSING")
    if deadline is None:
        failures.append("OFFICIAL_DEADLINE_MISSING")
    if scan_at and deadline and scan_at > deadline:
        failures.append("SOURCE_SCAN_AFTER_DEADLINE")
    if not str(data.get("deadline_source_url") or "").startswith("https://"):
        failures.append("OFFICIAL_DEADLINE_SOURCE_MISSING")

    categories = [dict(x) for x in data.get("categories") or [] if isinstance(x, Mapping)]
    by_category = {str(x.get("category") or "").upper(): x for x in categories}
    for category in REQUIRED_SOURCE_CATEGORIES:
        row = by_category.get(category)
        if row is None:
            failures.append("SOURCE_CATEGORY_MISSING:" + category)
            continue
        result = str(row.get("result") or "NOT_CHECKED").upper()
        attempted = _parse_time(row.get("attempted_at"))
        url = str(row.get("source_url") or "")
        if result not in VALID_RESULTS:
            failures.append("SOURCE_RESULT_INVALID:" + category)
        if attempted is None:
            failures.append("SOURCE_ATTEMPT_TIMESTAMP_MISSING:" + category)
        if not url.startswith("https://"):
            failures.append("SOURCE_URL_MISSING:" + category)
        if result in {"INACCESSIBLE", "NOT_CHECKED"} and require_full:
            failures.append("SOURCE_CATEGORY_NOT_VERIFIED:" + category)

    clubs = [dict(x) for x in data.get("clubs") or [] if isinstance(x, Mapping)]
    club_ids = [str(x.get("official_club_id") or "").strip() for x in clubs]
    if len(clubs) != 20 or any(not x for x in club_ids) or len(set(club_ids)) != 20:
        failures.append("ALL_20_CLUBS_IDENTITY_COVERAGE_INVALID")
    for row in clubs:
        club_id = str(row.get("official_club_id") or "UNKNOWN")
        result = str(row.get("result") or "NOT_CHECKED").upper()
        if result not in VALID_RESULTS:
            failures.append("CLUB_RESULT_INVALID:" + club_id)
        if not _parse_time(row.get("attempted_at")):
            failures.append("CLUB_ATTEMPT_TIMESTAMP_MISSING:" + club_id)
        if result in {"INACCESSIBLE", "NOT_CHECKED"} and require_full:
            failures.append("CLUB_NOT_VERIFIED:" + club_id)
        if result == "CHECKED_WITH_FINDINGS" and not isinstance(row.get("claims"), list):
            failures.append("CLUB_CLAIMS_MISSING:" + club_id)
        if result == "CHECKED_NO_CHANGE" and not str(row.get("evidence_url") or "").startswith("https://"):
            failures.append("CLUB_NO_CHANGE_WITHOUT_EVIDENCE:" + club_id)

    if not data.get("scan_id"):
        failures.append("SOURCE_SCAN_ID_MISSING")
    unique = list(dict.fromkeys(failures))
    return {
        "contract": "V12_NEWS_SOURCE_COVERAGE_V1",
        "status": "PASS" if not unique else "FAIL",
        "failures": unique,
        "scan_id": data.get("scan_id"),
        "scan_at": data.get("scan_at"),
        "club_count": len(clubs),
        "club_verified_count": sum(
            str(x.get("result") or "").upper() in {"CHECKED_WITH_FINDINGS", "CHECKED_NO_CHANGE"}
            for x in clubs
        ),
        "category_count": len(by_category),
        "required_category_count": len(REQUIRED_SOURCE_CATEGORIES),
        "decision_authority": False,
    }


def validate_independent_counterpart_coverage(
    counterpart: Mapping[str, Any] | None,
    *,
    require_full: bool = True,
) -> dict[str, Any]:
    """Require an auditable counterpart assessment for each decision domain."""
    data = dict(counterpart or {})
    failures: list[str] = []
    assessments = [
        dict(x) for x in data.get("assessments") or [] if isinstance(x, Mapping)
    ]
    by_domain = {str(x.get("domain") or "").upper(): x for x in assessments}
    for domain in REQUIRED_DECISION_DOMAINS:
        row = by_domain.get(domain)
        if row is None:
            failures.append("COUNTERPART_DOMAIN_MISSING:" + domain)
            continue
        verdict = str(row.get("verdict") or "NOT_CHECKED").upper()
        if verdict not in {"CONFIRMS", "CHALLENGES", "INCONCLUSIVE", "NOT_CHECKED"}:
            failures.append("COUNTERPART_VERDICT_INVALID:" + domain)
        sources = [dict(x) for x in row.get("sources") or [] if isinstance(x, Mapping)]
        valid_sources = [
            x for x in sources
            if str(x.get("url") or "").startswith("https://")
            and _parse_time(x.get("as_of")) is not None
            and str(x.get("independence_group") or "").strip()
        ]
        if require_full and (verdict in {"NOT_CHECKED", "INCONCLUSIVE"} or len({
            str(x.get("independence_group")) for x in valid_sources
        }) < 2):
            failures.append("COUNTERPART_INDEPENDENT_EVIDENCE_INCOMPLETE:" + domain)
        if not row.get("action"):
            failures.append("COUNTERPART_ACTION_MISSING:" + domain)
    if not data.get("assessment_at"):
        failures.append("COUNTERPART_ASSESSMENT_TIMESTAMP_MISSING")
    unique = list(dict.fromkeys(failures))
    return {
        "contract": "V12_INDEPENDENT_COUNTERPART_COVERAGE_V1",
        "status": "PASS" if not unique else "FAIL",
        "failures": unique,
        "assessment_count": len(assessments),
        "required_domain_count": len(REQUIRED_DECISION_DOMAINS),
        "decision_authority": False,
    }


def render_news_source_coverage(coverage: Mapping[str, Any] | None) -> list[str]:
    """Render an honest, compact, source-auditable section for report S04."""
    data = dict(coverage or {})
    checked = validate_news_source_coverage(data, require_full=True)
    lines = [
        "### NEWS & SOURCE COVERAGE",
        f"Gate: {checked['status']} | scan {checked.get('scan_at') or 'NOT RECORDED'} | "
        f"clubs verified {checked['club_verified_count']}/20 | categories "
        f"{checked['category_count']}/{checked['required_category_count']}",
    ]
    if checked["failures"]:
        lines.append("Coverage gaps: " + ", ".join(checked["failures"]))
    for row in data.get("categories") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- {row.get('category') or 'UNKNOWN'}: {row.get('result') or 'NOT_CHECKED'}; "
            f"attempted {row.get('attempted_at') or 'NOT RECORDED'}; "
            f"source {row.get('source_url') or 'URL UNAVAILABLE'}"
        )
    for row in data.get("clubs") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- Club {row.get('club_name') or row.get('official_club_id') or 'UNKNOWN'}: "
            f"{row.get('result') or 'NOT_CHECKED'}; "
            f"{row.get('summary') or 'NO VERIFIED UPDATE'}; "
            f"source {row.get('evidence_url') or 'URL UNAVAILABLE'}"
        )
    return lines
