import json

from src.engines import authenticated_official as ao
from src.sources import official_auth
from src.sources.official_auth import AuthMaterial, safe_get


class _RedirectResponse:
    def __init__(self, status_code=302):
        self.status_code = status_code
        self.headers = {"Location": "https://unexpected.example/secret-target"}

    def raise_for_status(self):
        raise AssertionError("redirect must be handled before raise_for_status")

    def json(self):
        raise AssertionError("redirect response body must not be parsed")


def test_authenticated_redirect_is_never_followed_or_exposed(monkeypatch):
    observed = {}

    def fake_get(url, headers, timeout, allow_redirects):
        observed["allow_redirects"] = allow_redirects
        observed["cookie"] = headers.get("Cookie")
        return _RedirectResponse(302)

    monkeypatch.setattr(official_auth.requests, "get", fake_get)
    material = AuthMaterial(mode="session_cookie", headers={"Cookie": "session=secret"})
    payload, health = safe_get("me/", material)

    assert payload is None
    assert observed["allow_redirects"] is False
    assert observed["cookie"] == "session=secret"
    assert health["status"] == "REDIRECT_REJECTED"
    assert health["http_status"] == 302
    assert "unexpected.example" not in json.dumps(health)
    assert "session=secret" not in json.dumps(health)


def test_authenticated_307_is_policy_rejection_not_retryable_generic_failure(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, headers, timeout, allow_redirects):
        calls["count"] += 1
        return _RedirectResponse(307)

    monkeypatch.setattr(official_auth.requests, "get", fake_get)
    material = AuthMaterial(mode="bearer_token", headers={"X-API-Authorization": "Bearer secret"})
    payload, health = safe_get("me/", material, retries=3)

    assert payload is None
    assert health["status"] == "REDIRECT_REJECTED"
    assert health["attempts"] == 1
    assert calls["count"] == 1


def test_auth_engine_exposes_redirect_rejection_without_raw_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(ao, "DATA", tmp_path)
    (tmp_path / "team.json").write_text(json.dumps({"squad": [{"element": 1}]}))
    (tmp_path / "latest.json").write_text(json.dumps({}))
    monkeypatch.setattr(
        ao,
        "auth_material_from_env",
        lambda: AuthMaterial(mode="session_cookie", headers={"Cookie": "secret=never-persist"}),
    )
    monkeypatch.setattr(
        ao,
        "safe_get",
        lambda path, material: (
            None,
            {"status": "REDIRECT_REJECTED", "http_status": 302, "error": "authenticated redirect rejected by policy"},
        ),
    )

    summary = ao.run()
    assert summary["state"] == "REDIRECT_REJECTED"
    assert summary["policy"]["redirects_followed"] is False
    assert summary["policy"]["redirects_rejected"] is True
    persisted = (tmp_path / "auth.json").read_text()
    assert "secret=never-persist" not in persisted
