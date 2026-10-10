from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace

from src.runtime_v6.domains.report_plane.auth_probe import probe


class FakeClient:
    def __init__(self, me, team=None, *, configured=True):
        self.auth_configuration_state = "CONFIGURED" if configured else "INVALID"
        self.auth_available = configured
        self.auth_material = SimpleNamespace(mode="bearer_token") if configured else None
        self.me_response, self.team_response = me, team
        self.team_calls = 0

    def me(self):
        return self.me_response

    def my_team(self, entry):
        assert entry == 3462711
        self.team_calls += 1
        return self.team_response


def response(code, payload=None, status=None):
    return {"http_status": code, "status": status or ("LIVE" if code == 200 else "AUTH_REJECTED"), "payload": payload}


def test_401_is_distinct_from_403_and_skips_private_team():
    for code, result in [(401, "AUTH_ME_HTTP_401_UNAUTHORIZED"), (403, "AUTH_ME_HTTP_403_FORBIDDEN")]:
        client = FakeClient(response(code))
        outcome = probe(client, 3462711, environ={"FPL_ACCESS_TOKEN": "dummy"})
        assert outcome["probe_state"] == result
        assert outcome["me_http"] == code
        assert outcome["my_team_result"] == "NOT_CALLED"
        assert client.team_calls == 0


def test_identity_mismatch_is_fail_closed():
    client = FakeClient(response(200, {"player": {"entry": 99999}}))
    outcome = probe(client, 3462711, environ={})
    assert outcome["probe_state"] == "AUTH_ENTRY_MISMATCH"
    assert client.team_calls == 0


def test_redirect_does_not_follow_or_promote_auth():
    client = FakeClient(response(302, status="REDIRECT_REJECTED"))
    assert probe(client, 3462711, environ={})["probe_state"] == "AUTH_ME_HTTP_3XX_REDIRECT"
    assert client.team_calls == 0


def test_both_authenticated_endpoints_200_prove_auth_only_with_correct_team():
    picks = [{"element": n, "selling_price": 50, "purchase_price": 49} for n in range(1, 16)]
    client = FakeClient(response(200, {"player": {"entry": 3462711}}), response(200, {"picks": picks, "transfers": {"bank": 2}}))
    outcome = probe(client, 3462711, environ={"FPL_ACCESS_TOKEN": "fake.not-real.token"})
    assert outcome["probe_state"] == "AUTH_AVAILABLE"
    assert outcome["my_team_http"] == 200
    assert outcome["private_squad_15_valid"]
    assert outcome["bank_available"]
    assert outcome["selling_prices_15_valid"]
    assert not outcome["free_transfers_field_available"]
    assert "bearer fake" not in json.dumps(outcome).lower()


def test_jwt_exp_claim_is_diagnostic_not_authority():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) - 120}).encode()).decode().rstrip("=")
    token = "header." + payload + ".signature"
    client = FakeClient(response(401))
    outcome = probe(client, 3462711, environ={"FPL_ACCESS_TOKEN": token})
    assert outcome["jwt_expiry_state"] == "EXPIRED_BY_CLAIM"
    assert outcome["probe_state"] == "AUTH_ME_HTTP_401_UNAUTHORIZED"
    assert token not in json.dumps(outcome)


def test_duplicate_bearer_prefix_is_diagnosed_without_printing_secret():
    client = FakeClient(response(401))
    outcome = probe(client, 3462711, environ={"FPL_ACCESS_TOKEN": "Bearer secret"})
    assert outcome["bearer_has_duplicate_prefix"] is True
    assert "secret" not in json.dumps(outcome)
