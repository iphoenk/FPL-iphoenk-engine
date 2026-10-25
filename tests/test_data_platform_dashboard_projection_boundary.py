from __future__ import annotations

import json
import logging
import socket

import pytest

from src.runtime_v6.domains.publication.dashboard_facts_projection import (
    PROJECTION_VERSION,
    ProjectionBoundaryError,
    build_dashboard_facts_projection,
)
from src.runtime_v6.registry import ZERO_AUTHORITY_KEYS

NOW = "2026-10-25T12:00:00Z"
SECRET = "ghp_SyntheticSecretValue123456"
ALLOW = {"health": ["overall"], "identity": ["coverage_ratio"], "coverage": ["players"], "provenance": ["source"],
         "official_facts": ["current_gw"]}


def _snap(**over):
    base = {
        "assessment": {"state": "FRESH", "usable": True, "generated_at": "2026-10-25T11:50:00+00:00",
                       "age_minutes": 10.0, "freshness_basis": "PUBLICATION_TIME_ONLY"},
        "health": {"overall": "GREEN", "scheduler_control": {"x": 1}},
        "identity": {"consistent": True, "coverage_ratio": 1.0},
        "coverage": {"players": 667}, "provenance": {"source": "official_fpl"},
        "official_facts": {"current_gw": 8, "picks": [1, 2, 3]},
        "optional": {"news": {"status": "AVAILABLE"}},
    }
    base.update(over)
    return base


def test_exact_allowlist_nothing_else_is_copied():
    out = build_dashboard_facts_projection(_snap(), ALLOW, now=NOW)
    assert out["sections"] == {"health": {"overall": "GREEN"}, "identity": {"coverage_ratio": 1.0},
                               "coverage": {"players": 667}, "provenance": {"source": "official_fpl"},
                               "official_facts": {"current_gw": 8}}
    text = json.dumps(out)
    assert "scheduler_control" not in text and "picks" not in text


def test_unknown_private_field_in_an_allowlisted_section_is_rejected():
    snap = _snap(official_facts={"current_gw": 8, "manager_plan": {"transfers": []}})
    with pytest.raises(ProjectionBoundaryError):
        build_dashboard_facts_projection(snap, {"official_facts": ["current_gw", "manager_plan"]}, now=NOW)
    nested = _snap(official_facts={"current_gw": {"deep": {"picks": [1]}}})
    with pytest.raises(ProjectionBoundaryError):
        build_dashboard_facts_projection(nested, ALLOW, now=NOW)


def test_sections_outside_the_permitted_set_cannot_be_allowlisted():
    with pytest.raises(ProjectionBoundaryError):
        build_dashboard_facts_projection(_snap(), {"picks": ["x"]}, now=NOW)


def test_synthetic_secret_never_reaches_output_error_or_logs(caplog, capsys):
    snap = _snap(official_facts={"current_gw": SECRET})
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProjectionBoundaryError) as err:
            build_dashboard_facts_projection(snap, ALLOW, now=NOW)
    assert SECRET not in str(err.value) and SECRET not in caplog.text
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    clean = build_dashboard_facts_projection(_snap(), ALLOW, now=NOW)
    assert SECRET not in json.dumps(clean)


def test_role_has_zero_authority():
    out = build_dashboard_facts_projection(_snap(), ALLOW, now=NOW)
    assert out["authority"]["role"] == "FACTS_ONLY"
    assert all(out["authority"][k] == "NONE" for k in ZERO_AUTHORITY_KEYS)
    assert out["publication"] == {"public_export": False, "additive": True}
    assert out["version"] == PROJECTION_VERSION


def test_wrong_identity_stale_and_unknown_have_clear_status():
    assert build_dashboard_facts_projection(_snap(identity={"consistent": False}), ALLOW, now=NOW)["status"] == "IDENTITY_UNVERIFIED"
    stale = _snap(assessment={"state": "STALE", "usable": False})
    assert build_dashboard_facts_projection(stale, ALLOW, now=NOW)["status"] == "STALE"
    assert build_dashboard_facts_projection({}, ALLOW, now=NOW)["status"] == "UNKNOWN"
    odd = _snap(assessment={"state": "WEIRD"})
    assert build_dashboard_facts_projection(odd, ALLOW, now=NOW)["status"] == "UNKNOWN"
    fresh_unusable = _snap(assessment={"state": "FRESH", "usable": False})
    assert build_dashboard_facts_projection(fresh_unusable, ALLOW, now=NOW)["status"] == "UNKNOWN"


def test_complete_facts_are_not_gated_by_optional_news():
    with_news = build_dashboard_facts_projection(_snap(), ALLOW, now=NOW)
    no_news = build_dashboard_facts_projection(_snap(optional={}), ALLOW, now=NOW)
    broken_news = build_dashboard_facts_projection(_snap(optional={"news": {"status": "ERROR"}}), ALLOW, now=NOW)
    for out in (no_news, broken_news):
        assert out["status"] == with_news["status"] == "FRESH" and out["sections"] == with_news["sections"]
    assert with_news["optional_sections"]["news"]["available"] is True
    assert no_news["optional_sections"]["news"]["available"] is False


def test_projection_makes_no_network_calls(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    assert build_dashboard_facts_projection(_snap(), ALLOW, now=NOW)["status"] == "FRESH"
