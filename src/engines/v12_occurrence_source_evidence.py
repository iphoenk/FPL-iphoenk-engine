"""Occurrence-bound source evidence admission for V12.

This is not a web scraper. The V6 provider trace proves acquisition, not news
review. Only a verified Official FPL bootstrap inspection and explicitly
recorded, same-occurrence external source reviews can enter the source gate.
Missing reviews remain FAIL. No model, scheduler or privacy authority here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.engines.v12_independent_counterpart import assess_counterpart
from src.engines.v12_source_coverage import (
    REQUIRED_DECISION_DOMAINS,
    REQUIRED_SOURCE_CATEGORIES,
    validate_independent_counterpart_coverage,
    validate_news_source_coverage,
)
from src.engines.v12_v6_source_trace import verified_official_deadline_source_coverage

REVIEW_FILE = "data/v6/evidence/v12_source_reviews/latest.json"
REVIEW_CONTRACT = "V12_OCCURRENCE_SOURCE_REVIEWS_V1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _dt(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo and dt.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _in_window(value: Any, *, slot: datetime, deadline: datetime) -> bool:
    observed = _dt(value)
    return observed is not None and (
        slot - timedelta(minutes=90) <= observed <= slot + timedelta(minutes=15)
        and observed <= deadline
    )


def _capture_verified(row: Mapping[str, Any], *, root: Path, url: str,
                      observed_at: Any, slot: datetime, deadline: datetime) -> bool:
    """Verify bytes of an actual stored capture; a supplied digest is not proof."""
    relative = str(row.get("capture_path") or "")
    prefix = "data/v6/evidence/v12_source_reviews/captures/"
    if not relative.startswith(prefix) or not relative.endswith(".json"):
        return False
    base = (root / prefix).resolve()
    file = (root / relative).resolve()
    if not file.is_relative_to(base):
        return False
    try:
        if not file.is_file() or file.stat().st_size > 65536:
            return False
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("capture_sha256"):
            return False
        payload = json.loads(raw)
        body = payload.get("reviewed_text")
        return (
            payload.get("contract") == "V12_SOURCE_CAPTURE_V1"
            and payload.get("url") == url
            and payload.get("review_status") == "REVIEWED"
            and payload.get("observed_at") == observed_at
            and _in_window(observed_at, slot=slot, deadline=deadline)
            and isinstance(body, str) and 0 < len(body) <= 16384
            and hashlib.sha256(body.encode("utf-8")).hexdigest()
                == payload.get("reviewed_text_sha256")
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _valid_reviewed_news(review: Mapping[str, Any], *, root: Path, slot: datetime, deadline: datetime,
                         club_ids: set[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    seen_categories: set[str] = set()
    for row in review.get("categories") or []:
        if not isinstance(row, Mapping):
            errors.append("REVIEW_CATEGORY_INVALID")
            continue
        name = str(row.get("category") or "")
        if name in seen_categories or name not in REQUIRED_SOURCE_CATEGORIES:
            errors.append("REVIEW_CATEGORY_ID_INVALID")
        seen_categories.add(name)
        if not _in_window(row.get("attempted_at"), slot=slot, deadline=deadline):
            errors.append("REVIEW_CATEGORY_OUT_OF_WINDOW:" + name)
        if not _capture_verified(row, root=root, url=str(row.get("source_url") or ""),
                                 observed_at=row.get("attempted_at"), slot=slot, deadline=deadline):
            errors.append("REVIEW_CATEGORY_CAPTURE_INVALID:" + name)
        if not str(row.get("source_url") or "").startswith("https://"):
            errors.append("REVIEW_CATEGORY_URL_INVALID:" + name)
        if row.get("result") not in ("CHECKED_WITH_FINDINGS", "CHECKED_NO_CHANGE"):
            errors.append("REVIEW_CATEGORY_NOT_VERIFIED:" + name)
    seen_clubs: set[str] = set()
    for row in review.get("clubs") or []:
        if not isinstance(row, Mapping):
            errors.append("REVIEW_CLUB_INVALID")
            continue
        cid = str(row.get("official_club_id") or "")
        if cid in seen_clubs or cid not in club_ids:
            errors.append("REVIEW_CLUB_ID_INVALID:" + cid)
        seen_clubs.add(cid)
        if not _in_window(row.get("attempted_at"), slot=slot, deadline=deadline):
            errors.append("REVIEW_CLUB_OUT_OF_WINDOW:" + cid)
        if not _capture_verified(row, root=root, url=str(row.get("evidence_url") or ""),
                                 observed_at=row.get("attempted_at"), slot=slot, deadline=deadline):
            errors.append("REVIEW_CLUB_CAPTURE_INVALID:" + cid)
        if not str(row.get("evidence_url") or "").startswith("https://"):
            errors.append("REVIEW_CLUB_URL_INVALID:" + cid)
        if row.get("result") not in ("CHECKED_WITH_FINDINGS", "CHECKED_NO_CHANGE"):
            errors.append("REVIEW_CLUB_NOT_VERIFIED:" + cid)
    return not errors, errors


def _verified_counterparts(review: Mapping[str, Any], *, root: Path, slot: datetime,
                           deadline: datetime) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    assessments = []
    seen: set[str] = set()
    for row in review.get("assessments") or []:
        if not isinstance(row, Mapping):
            errors.append("COUNTERPART_ROW_INVALID")
            continue
        domain = str(row.get("domain") or "")
        if domain not in REQUIRED_DECISION_DOMAINS or domain in seen:
            errors.append("COUNTERPART_DOMAIN_INVALID:" + domain)
            continue
        seen.add(domain)
        canonical = dict(row.get("canonical") or {})
        samples = [dict(x) for x in row.get("counterparts") or [] if isinstance(x, Mapping)]
        if not samples or not _in_window(canonical.get("as_of"), slot=slot, deadline=deadline):
            errors.append("COUNTERPART_CANONICAL_ASOF_INVALID:" + domain)
            continue
        if _dt(canonical.get("deadline")) != deadline:
            errors.append("COUNTERPART_DEADLINE_MISMATCH:" + domain)
            continue
        comparable = [
            x for x in samples
            if str(x.get("url") or "").startswith("https://")
            and _capture_verified(x, root=root, url=str(x.get("url") or ""),
                                  observed_at=x.get("as_of"), slot=slot, deadline=deadline)
        ]
        result = assess_counterpart(canonical, comparable)
        evaluated = result.get("comparisons") or []
        groups = {str(x.get("independence_group")) for x in evaluated}
        if len(groups) < 2 or result.get("verdict") not in ("CONFIRMED", "CONTESTED"):
            errors.append("COUNTERPART_NOT_TWO_COMPARABLE_GROUPS:" + domain)
            continue
        matched = [
            x for x in comparable
            if str(x.get("independence_group")) in groups
            and x.get("metric") == canonical.get("metric")
            and x.get("horizon") == canonical.get("horizon")
        ]
        assessments.append({
            "domain": domain,
            "verdict": "CONFIRMS" if result["verdict"] == "CONFIRMED" else "CHALLENGES",
            "action": str(row.get("action") or "REVIEW"),
            "sources": [{"url": x["url"], "as_of": x["as_of"],
                         "independence_group": x["independence_group"]}
                        for x in matched],
        })
    return {"assessment_at": slot.isoformat(), "assessments": assessments}, errors


def build_occurrence_source_evidence(*, runtime_data_root: Path,
                                     trace: Mapping[str, Any],
                                     bootstrap: Mapping[str, Any],
                                     report_slot: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return real admitted news, counterpart and safe diagnostic status.

    No unreviewed V6 provider/category is promoted to a news check. An optional
    upstream source-review receipt must bind the exact current V6 publication.
    """
    base = verified_official_deadline_source_coverage(trace)
    counterpart: dict[str, Any] = {}
    diagnostic: dict[str, Any] = {"contract": REVIEW_CONTRACT, "status": "UNAVAILABLE",
                                  "review_path": REVIEW_FILE, "failures": []}
    slot = _dt(report_slot)
    verified = dict(trace.get("official_deadline_evidence") or {})
    deadline = _dt(verified.get("deadline_utc"))
    provider = next((dict(p) for p in trace.get("providers") or []
                     if isinstance(p, Mapping) and p.get("source_id") == "official_fpl"), None)
    if not (slot and deadline and trace.get("status") == "PASS" and provider
            and trace.get("official_deadline_check") == "VERIFIED_FPL_BOOTSTRAP_FIELD"):
        diagnostic["status"] = "V6_IDENTITY_OR_DEADLINE_NOT_PROVEN"
        return base, counterpart, diagnostic
    checked = provider.get("checked_at")
    snapshot = next((s for s in provider.get("snapshot_ids") or []
                     if isinstance(s, str) and s.startswith("official_fpl:bootstrap:")), None)
    elements = bootstrap.get("elements")
    if (_in_window(checked, slot=slot, deadline=deadline) and snapshot
            and provider.get("health") == "GREEN"
            and provider.get("availability") == "AVAILABLE"
            and isinstance(elements, list) and elements):
        claims = [
            {"element_id": item.get("id"), "news": str(item["news"])[:500]}
            for item in elements if isinstance(item, Mapping)
            and isinstance(item.get("news"), str) and item["news"].strip()
            and (_dt(item.get("news_added")) is None or _dt(item["news_added"]) <= _dt(checked))
        ]
        # Actual inspection of the official snapshot, NOT club news or social.
        result = "CHECKED_WITH_FINDINGS" if claims else "CHECKED_NO_CHANGE"
        proof = hashlib.sha256((report_slot + "|" + snapshot + "|" + str(checked)).encode()).hexdigest()
        base.update({
            "scan_id": "official-fpl-bootstrap:" + proof,
            "scan_at": checked,
            "source_scan_scope": "OFFICIAL_FPL_BOOTSTRAP_ONLY",
            "categories": [{
                "category": "OFFICIAL_PL_FPL", "result": result,
                "attempted_at": checked, "source_url": "https://fantasy.premierleague.com/api/bootstrap-static/",
                "source_snapshot_id": snapshot,
                "claims": claims[:30], "total_claim_count": len(claims),
                "review_binding_sha256": proof,
            }],
        })
        diagnostic["status"] = "OFFICIAL_FPL_SNAPSHOT_REVIEWED_PARTIAL"
    # Actual independent source reviews are supplied by a separate governed V6
    # producer. Nothing is assumed present merely because a provider was GREEN.
    candidate = runtime_data_root / REVIEW_FILE
    try:
        receipt = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return base, counterpart, diagnostic
    if not isinstance(receipt, dict):
        diagnostic["status"] = "REVIEW_RECEIPT_INVALID"
        return base, counterpart, diagnostic
    if (receipt.get("contract") != REVIEW_CONTRACT
            or receipt.get("report_slot") != report_slot
            or str(receipt.get("v6_publication_run_id") or "") != str(trace.get("v6_publication_run_id") or "")
            or not _in_window(receipt.get("reviewed_at"), slot=slot, deadline=deadline)):
        diagnostic.update(status="REVIEW_RECEIPT_BINDING_FAILED",
                          failures=["CONTRACT_SLOT_V6_RUN_OR_TIME_MISMATCH"])
        return base, counterpart, diagnostic
    news = dict(receipt.get("news_source_coverage") or {})
    teams = bootstrap.get("teams")
    official_ids = {str(t.get("id")) for t in teams or [] if isinstance(t, Mapping)}
    if len(official_ids) != 20:
        diagnostic.update(status="OFFICIAL_CLUB_IDENTITIES_INCOMPLETE")
        return base, counterpart, diagnostic
    valid_news, errors = _valid_reviewed_news(news, root=runtime_data_root, slot=slot, deadline=deadline, club_ids=official_ids)
    if not valid_news:
        diagnostic.update(status="REVIEW_NEWS_REJECTED", failures=errors[:30])
        return base, counterpart, diagnostic
    candidate_news = {**base, **news}
    candidate_news["deadline"] = base.get("deadline")
    candidate_news["deadline_source_url"] = base.get("deadline_source_url")
    candidate_news["scan_at"] = receipt["reviewed_at"]
    candidate_news["scan_id"] = str(receipt.get("review_id") or "")
    if not candidate_news["scan_id"]:
        diagnostic.update(status="REVIEW_SCAN_ID_MISSING")
        return base, counterpart, diagnostic
    candidate_counter, counterpart_errors = _verified_counterparts(
        dict(receipt.get("independent_counterpart_coverage") or {}),
        root=runtime_data_root, slot=slot, deadline=deadline,
    )
    if counterpart_errors:
        diagnostic.update(status="REVIEW_COUNTERPART_PARTIAL",
                          failures=counterpart_errors[:30])
    elif not candidate_counter["assessments"]:
        diagnostic.update(status="REVIEW_COUNTERPART_NOT_PROVIDED")
    else:
        counterpart = candidate_counter
    # Source evidence remains FAIL whenever any required category, club, or
    # independent counterpart is missing. Never reclassify without validators.
    base = candidate_news
    source_check = validate_news_source_coverage(base, require_full=True)
    counter_check = validate_independent_counterpart_coverage(counterpart, require_full=True)
    if source_check["status"] == "PASS" and counter_check["status"] == "PASS":
        diagnostic["status"] = "VERIFIED_SOURCE_REVIEWS_COMPLETE"
        diagnostic["failures"] = []
    else:
        diagnostic["status"] = "REVIEW_PARTIAL_FAIL_CLOSED"
        diagnostic["failures"] = (source_check["failures"] + counter_check["failures"])[:30]
    return base, counterpart, diagnostic
