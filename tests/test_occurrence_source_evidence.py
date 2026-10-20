from __future__ import annotations

import json
import hashlib

from src.engines.v12_occurrence_source_evidence import (
    REVIEW_CONTRACT,
    REVIEW_FILE,
    build_occurrence_source_evidence,
)
from src.engines.v12_source_coverage import (
    REQUIRED_DECISION_DOMAINS,
    REQUIRED_SOURCE_CATEGORIES,
    validate_independent_counterpart_coverage,
    validate_news_source_coverage,
)

SLOT = "2026-10-20T15:00:00+07:00"
CHECKED = "2026-10-20T08:02:37+00:00"
DEADLINE = "2026-10-24T00:30:00+07:00"


def _trace():
    return {
        "status": "PASS",
        "v6_publication_run_id": "39390537219",
        "official_deadline_check": "VERIFIED_FPL_BOOTSTRAP_FIELD",
        "official_deadline_evidence": {
            "deadline_utc": "2026-10-23T17:30:00+00:00",
            "deadline_source_url": "https://fantasy.premierleague.com/api/bootstrap-static/",
        },
        "providers": [{
            "source_id": "official_fpl",
            "health": "GREEN",
            "availability": "AVAILABLE",
            "checked_at": CHECKED,
            "snapshot_ids": ["official_fpl:bootstrap:test"],
        }],
    }


def _bootstrap():
    return {
        "teams": [{"id": i, "name": "Team " + str(i)} for i in range(1, 21)],
        "elements": [{"id": 411, "news": "Unspecified injury",
                      "news_added": "2026-10-19T13:00:10+00:00"}],
    }


def test_official_bootstrap_is_real_partial_source_review(tmp_path):
    news, counterpart, diagnosis = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert news["scan_at"] == CHECKED
    assert news["scan_id"].startswith("official-fpl-bootstrap:")
    assert news["categories"][0]["category"] == "OFFICIAL_PL_FPL"
    assert news["categories"][0]["total_claim_count"] == 1
    assert news["source_scan_scope"] == "OFFICIAL_FPL_BOOTSTRAP_ONLY"
    assert validate_news_source_coverage(news)["status"] == "FAIL"
    assert "SOURCE_CATEGORY_MISSING:OFFICIAL_CLUBS" in validate_news_source_coverage(news)["failures"]
    assert counterpart == {}
    assert diagnosis["status"] == "OFFICIAL_FPL_SNAPSHOT_REVIEWED_PARTIAL"


def test_missing_or_unverified_v6_never_creates_scan(tmp_path):
    trace = _trace()
    trace["status"] = "FAIL"
    news, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=trace,
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert not news
    assert not counterpart
    assert diagnostic["status"] == "V6_IDENTITY_OR_DEADLINE_NOT_PROVEN"


def test_stale_official_provider_does_not_count_as_review(tmp_path):
    trace = _trace()
    trace["providers"][0]["checked_at"] = "2026-10-19T04:00:00+00:00"
    news, _, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=trace,
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert "scan_id" not in news
    assert diagnostic["status"] == "UNAVAILABLE"


def _receipt():
    categories = [
        {
            "category": category,
            "result": "CHECKED_WITH_FINDINGS",
            "attempted_at": CHECKED,
            "source_url": "https://example.com/" + category.lower(),
            "capture_sha256": "a" * 64,
        }
        for category in REQUIRED_SOURCE_CATEGORIES
    ]
    clubs = [
        {
            "official_club_id": str(i),
            "club_name": "Team " + str(i),
            "result": "CHECKED_NO_CHANGE",
            "attempted_at": CHECKED,
            "evidence_url": "https://example.com/club/" + str(i),
            "capture_sha256": "a" * 64,
        }
        for i in range(1, 21)
    ]
    counterparts = []
    for domain in REQUIRED_DECISION_DOMAINS:
        counterparts.append({
            "domain": domain,
            "action": "REVIEW",
            "canonical": {
                "subject": "Canonical " + domain, "metric": "xPts",
                "value": 5.0, "horizon": "GW8",
                "as_of": CHECKED, "deadline": DEADLINE,
            },
            "counterparts": [
                {
                    "source": "Provider A",
                    "independence_group": "a",
                    "url": "https://example.com/a/" + domain,
                    "capture_sha256": "a" * 64,
                    "as_of": CHECKED, "metric": "xPts", "horizon": "GW8",
                    "value": 4.8,
                },
                {
                    "source": "Provider B",
                    "independence_group": "b",
                    "url": "https://example.net/b/" + domain,
                    "capture_sha256": "b" * 64,
                    "as_of": CHECKED, "metric": "xPts", "horizon": "GW8",
                    "value": 5.1,
                },
            ],
        })
    return {
        "contract": REVIEW_CONTRACT,
        "report_slot": SLOT,
        "v6_publication_run_id": "39390537219",
        "review_id": "test-source-review",
        "reviewed_at": CHECKED,
        "news_source_coverage": {"categories": categories, "clubs": clubs},
        "independent_counterpart_coverage": {"assessments": counterparts},
    }


def _write_receipt(tmp_path, receipt):
    prefix = "data/v6/evidence/v12_source_reviews/captures/"
    samples = []
    for row in receipt["news_source_coverage"]["categories"]:
        samples.append((row, row["source_url"], row["attempted_at"]))
    for row in receipt["news_source_coverage"]["clubs"]:
        samples.append((row, row["evidence_url"], row["attempted_at"]))
    for review in receipt["independent_counterpart_coverage"]["assessments"]:
        for row in review["counterparts"]:
            samples.append((row, row["url"], row["as_of"]))
    for index, (row, url, observed) in enumerate(samples):
        body = "Test fixture source capture from " + url
        payload = {
            "contract": "V12_SOURCE_CAPTURE_V1",
            "url": url,
            "review_status": "REVIEWED",
            "observed_at": observed,
            "reviewed_text": body,
            "reviewed_text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        raw = json.dumps(payload).encode("utf-8")
        relative = prefix + str(index) + ".json"
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        row["capture_path"] = relative
        row["capture_sha256"] = hashlib.sha256(raw).hexdigest()
    p = tmp_path / REVIEW_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(receipt), encoding="utf-8")


def test_full_real_review_receipt_is_admitted_for_independent_validator(tmp_path):
    _write_receipt(tmp_path, _receipt())
    news, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert diagnostic["status"] == "VERIFIED_SOURCE_REVIEWS_COMPLETE"
    assert validate_news_source_coverage(news)["status"] == "PASS"
    assert validate_independent_counterpart_coverage(counterpart)["status"] == "PASS"
    assert len(counterpart["assessments"]) == 5
    assert all(x["verdict"] == "CONFIRMS" for x in counterpart["assessments"])


def test_foreign_slot_review_is_rejected_and_official_partial_preserved(tmp_path):
    candidate = _receipt()
    candidate["report_slot"] = "2026-10-19T15:00:00+07:00"
    _write_receipt(tmp_path, candidate)
    news, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert diagnostic["status"] == "REVIEW_RECEIPT_BINDING_FAILED"
    assert news["source_scan_scope"] == "OFFICIAL_FPL_BOOTSTRAP_ONLY"
    assert not counterpart


def test_counterpart_metric_mismatch_does_not_gain_fake_green(tmp_path):
    candidate = _receipt()
    candidate["independent_counterpart_coverage"]["assessments"][0]["counterparts"][0]["metric"] = "xGI90"
    _write_receipt(tmp_path, candidate)
    _, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert diagnostic["status"] == "REVIEW_PARTIAL_FAIL_CLOSED"
    assert validate_independent_counterpart_coverage(counterpart)["status"] == "FAIL"


def test_nonexistent_capture_never_counts_as_independent_review(tmp_path):
    candidate = _receipt()
    _write_receipt(tmp_path, candidate)
    (tmp_path / candidate["news_source_coverage"]["clubs"][0]["capture_path"]).unlink()
    news, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert diagnostic["status"] == "REVIEW_NEWS_REJECTED"
    assert not counterpart
    assert news["source_scan_scope"] == "OFFICIAL_FPL_BOOTSTRAP_ONLY"


def test_tampered_capture_hash_fails_closed(tmp_path):
    candidate = _receipt()
    _write_receipt(tmp_path, candidate)
    path = tmp_path / candidate["news_source_coverage"]["categories"][0]["capture_path"]
    path.write_text('{"tampered":true}', encoding="utf-8")
    _, counterpart, diagnostic = build_occurrence_source_evidence(
        runtime_data_root=tmp_path, trace=_trace(),
        bootstrap=_bootstrap(), report_slot=SLOT,
    )
    assert diagnostic["status"] == "REVIEW_NEWS_REJECTED"
    assert not counterpart
