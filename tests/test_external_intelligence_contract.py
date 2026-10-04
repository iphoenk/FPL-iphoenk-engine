from datetime import datetime, timezone

import pytest

from src.models.external_intelligence import (
    ExternalObservation,
    reconcile_observations,
)


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _observation(**overrides):
    values = {
        "provider": "fpl_tactics",
        "source_class": "MODEL_CHALLENGER",
        "subject": "Player A",
        "metric": "xpts",
        "value": 7.2,
        "observed_at": "2026-10-04T11:30:00+00:00",
        "fetched_at": "2026-10-04T11:31:00+00:00",
        "freshness_state": "AVAILABLE_CURRENT",
        "provenance_url": "https://fpltactics.com/players",
        "root_family": "fpl_tactics_model",
        "independence_state": "INDEPENDENT_MODEL",
        "identity_state": "IDENTITY_RESOLVED",
        "parser_version": "fpl_tactics_v1",
    }
    values.update(overrides)
    return ExternalObservation(**values)


def test_official_derived_observation_is_not_independent():
    row = _observation(
        provider="fplanaly",
        root_family="official_fpl",
        independence_state="NOT_INDEPENDENT",
    )

    assert row.is_independent is False
    assert row.as_dict()["root_family"] == "official_fpl"


def test_stale_and_unavailable_observations_cannot_be_supporting_or_challenging():
    rows = [
        _observation(freshness_state="AVAILABLE_STALE"),
        _observation(freshness_state="UNAVAILABLE", value=None),
    ]

    result = reconcile_observations(rows, canonical_value=7.0, now=NOW)

    assert result["state"] == "STALE"
    assert result["eligible_count"] == 0


def test_same_root_family_is_not_pseudo_consensus():
    rows = [
        _observation(provider="fplanaly", root_family="official_fpl", independence_state="NOT_INDEPENDENT"),
        _observation(provider="fpl_analytics_dashboard", root_family="official_fpl", independence_state="NOT_INDEPENDENT"),
    ]

    result = reconcile_observations(rows, canonical_value=7.0, now=NOW)

    assert result["state"] == "NOT_INDEPENDENT"
    assert result["independent_root_families"] == []


def test_current_independent_model_challenge_is_categorical_only():
    result = reconcile_observations(
        [_observation(value=5.0)], canonical_value=7.0, now=NOW
    )

    assert result["state"] == "CHALLENGING"
    assert result["canonical_value"] == 7.0
    assert "external_score" not in result


def test_observation_rejects_unresolved_identity_for_current_evidence():
    with pytest.raises(ValueError, match="identity"):
        _observation(identity_state="IDENTITY_UNRESOLVED")
