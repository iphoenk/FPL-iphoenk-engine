import json

import pytest

from src.sources import official_first as mod
from src.utils import ROOT


def test_every_rec_through_40_has_explicit_official_disposition():
    payload = mod.load_official_first_coverage()
    health = mod.validate_official_first_coverage(payload)
    assert health["integrity_ok"] is True
    assert health["covered_recommendations"] == 41  # REC-09a and REC-09b are separate dispositions.
    assert set(payload["recommendations"]) == set(mod.EXPECTED_RECS)
    assert payload["recommendations"]["REC-01"]["applicability"] == "PUBLIC_FIRST"
    assert payload["recommendations"]["REC-23"]["applicability"] == "PUBLIC_THEN_PRIVATE_AUTH"
    assert payload["recommendations"]["REC-36"]["endpoints"] == ["entry_history", "entry_picks"]
    assert payload["recommendations"]["REC-38"]["applicability"] == "POLICY_ONLY"
    assert payload["recommendations"]["REC-39"]["applicability"] == "PUBLIC_THEN_PRIVATE_AUTH"
    assert payload["recommendations"]["REC-40"]["applicability"] == "NOT_APPLICABLE"


def test_fallback_is_closed_and_requires_explicit_official_reason():
    assert mod.official_attempt_required("REC-01") is True
    assert mod.fallback_allowed("REC-01", "OFFICIAL_UNAVAILABLE") is True
    assert mod.fallback_allowed("REC-01", "FIELD_NOT_EXPOSED") is True
    assert mod.fallback_allowed("REC-23", "PRIVATE_AUTH_REQUIRED") is True
    assert mod.fallback_allowed("REC-01", "OFFICIAL_NOT_APPLICABLE") is False
    assert mod.fallback_allowed("REC-01", "USE_PROXY_BECAUSE_EASIER") is False

    assert mod.official_attempt_required("REC-30") is False
    assert mod.fallback_allowed("REC-30", "OFFICIAL_NOT_APPLICABLE") is True
    assert mod.fallback_allowed("REC-30", "OFFICIAL_UNAVAILABLE") is False

    assert mod.official_attempt_required("REC-39") is True
    assert mod.fallback_allowed("REC-39", "PRIVATE_AUTH_REQUIRED") is True
    assert mod.official_attempt_required("REC-40") is False
    assert mod.fallback_allowed("REC-40", "OFFICIAL_NOT_APPLICABLE") is True


def test_invalid_or_incomplete_matrix_fails_closed():
    payload = json.loads((ROOT / "config" / "sources" / "official_first_coverage.json").read_text())
    payload["recommendations"].pop("REC-22")
    with pytest.raises(RuntimeError, match="coverage mismatch"):
        mod.validate_official_first_coverage(payload)


def test_source_registry_wires_official_first_policy_and_capabilities():
    registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    policy = registry["policy"]
    assert policy["official_first_rec_coverage_required"] is True
    assert policy["fallback_requires_explicit_official_disposition"] is True
    official = next(row for row in registry["sources"] if row["id"] == "official_fpl")
    capabilities = set(official["capabilities"])
    assert {"entry_history", "entry_picks", "entry_transfers", "element_summary", "event_live", "league_standings"} <= capabilities
