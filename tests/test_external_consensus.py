from src.engines.external_consensus import build_consensus


def _row(source, subject, direction, availability="AVAILABLE", factual=False):
    return {
        "source": source,
        "subject": subject,
        "availability": availability,
        "normalized_direction": direction,
        "signal": "synthetic test observation",
        "confidence": "MEDIUM",
        "possible_factual_error": factual,
    }


def test_all_external_sources_missing_is_fail_neutral():
    result = build_consensus({"observations": []})
    assert result["overall"] == "INSUFFICIENT_EVIDENCE"
    assert result["requires_official_refresh"] is False
    assert result["governance"]["outage_fail_neutral"] is True
    assert result["governance"]["native_truth_mutated"] is False
    assert result["governance"]["majority_vote_used"] is False


def test_available_support_is_align_without_overwriting_native():
    result = build_consensus({"observations": [_row("fffix", "captaincy", "SUPPORT_NATIVE")]})
    assert result["overall"] == "ALIGN"
    assert result["subjects"][0]["classification"] == "ALIGN"
    assert result["native_conclusion_frozen_before_overlay"] is True
    assert result["governance"]["advisory_only"] is True


def test_mixed_support_and_opposition_requires_review_divergence():
    result = build_consensus({
        "observations": [
            _row("fffix", "captaincy", "SUPPORT_NATIVE"),
            _row("ffhub", "captaincy", "OPPOSE_NATIVE"),
        ]
    })
    assert result["overall"] == "REVIEW_DIVERGENCE"
    assert result["subjects"][0]["classification"] == "REVIEW_DIVERGENCE"


def test_possible_factual_error_requests_official_refresh_not_external_override():
    result = build_consensus({
        "observations": [_row("ffscout", "availability", "OPPOSE_NATIVE", factual=True)]
    })
    assert result["requires_official_refresh"] is True
    assert result["governance"]["factual_divergence_action"] == "REFRESH_OFFICIAL_AND_RERUN_NATIVE"
    assert result["governance"]["native_truth_mutated"] is False


def test_stale_external_signal_cannot_count_as_current_opposition():
    result = build_consensus({
        "observations": [_row("onefpl", "price", "OPPOSE_NATIVE", availability="STALE")]
    })
    assert result["overall"] == "INSUFFICIENT_EVIDENCE"
    assert result["observations"][0]["normalized_direction"] == "INSUFFICIENT_EVIDENCE"
