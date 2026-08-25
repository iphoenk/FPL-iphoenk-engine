import json

import pytest

from src.sources.official_auth import AuthMaterial, AuthPolicyError, safe_get
from src.engines import authenticated_official as ao


def test_auth_client_rejects_non_allowlisted_route_before_network():
    material = AuthMaterial(mode="session_cookie", headers={"Cookie": "redacted=1"})
    with pytest.raises(AuthPolicyError):
        safe_get("entry/3462711/history/", material)


def test_safe_finance_only_exposes_authoritative_elements():
    payload = {
        "transfers": {"bank": 5, "value": 1000, "made": 2, "cost": 0},
        "picks": [
            {"element": 1, "purchase_price": 50, "selling_price": 51},
            {"element": 2, "purchase_price": 60, "selling_price": 61},
        ],
    }
    safe = ao._safe_finance(payload, {1})
    assert safe["bank"] == 5
    assert safe["exact_sell_total"] == 51
    assert safe["prices_for_authoritative_squad"] == [
        {"element": 1, "purchase_price": 50, "selling_price": 51}
    ]


def test_run_valid_auth_persists_safe_summary_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ao, "DATA", tmp_path)
    (tmp_path / "team.json").write_text(json.dumps({"squad": [{"element": 1}, {"element": 2}]}))
    (tmp_path / "latest.json").write_text(json.dumps({"engine_version": "3.7.0"}))

    monkeypatch.setattr(
        ao,
        "auth_material_from_env",
        lambda: AuthMaterial(mode="session_cookie", headers={"Cookie": "secret=never-persist"}),
    )

    def fake_get(path, material):
        assert material.headers["Cookie"] == "secret=never-persist"
        if path == "me/":
            return {"player": {"entry": 3462711}}, {"status": "LIVE", "http_status": 200}
        if path == "my-team/3462711/":
            return {
                "transfers": {"bank": 5, "value": 995, "made": 0, "cost": 0},
                "picks": [
                    {"element": 1, "purchase_price": 45, "selling_price": 45},
                    {"element": 2, "purchase_price": 55, "selling_price": 55},
                ],
                "chips": [{"name": "wildcard", "status_for_entry": "active", "played_by_entry": []}],
            }, {"status": "LIVE", "http_status": 200}
        if path == "entry/3462711/transfers-latest/":
            return [], {"status": "LIVE", "http_status": 200}
        raise AssertionError(path)

    monkeypatch.setattr(ao, "safe_get", fake_get)
    summary = ao.run()
    assert summary["state"] == "VALID"
    assert summary["verified_entry"] == 3462711
    assert summary["draft_integrity"]["matches_authoritative_squad"] is True
    assert summary["safe_finance"]["exact_sell_total"] == 100
    assert summary["raw_authenticated_payload_persisted"] is False

    persisted = (tmp_path / "auth.json").read_text()
    assert "secret=never-persist" not in persisted
    assert "player" not in persisted
    assert "picks" not in persisted


def test_entry_mismatch_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(ao, "DATA", tmp_path)
    (tmp_path / "team.json").write_text(json.dumps({"squad": [{"element": 1}]}))
    (tmp_path / "latest.json").write_text(json.dumps({}))
    monkeypatch.setattr(
        ao,
        "auth_material_from_env",
        lambda: AuthMaterial(mode="bearer_token", headers={"X-API-Authorization": "Bearer redacted"}),
    )
    monkeypatch.setattr(
        ao,
        "safe_get",
        lambda path, material: ({"player": {"entry": 999}}, {"status": "LIVE", "http_status": 200}),
    )
    summary = ao.run()
    assert summary["state"] == "ENTRY_MISMATCH"
    assert summary["endpoint_health"].keys() == {"me"}
