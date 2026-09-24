import base64
import json

import pytest

from src.engines.v12_deep_delivery import select_personal_evidence
from src.runtime_v6.domains.report_plane.manual_identity import (
    ManualIdentityError,
    decode_manual_identity_b64,
)


def _manual_payload(gw=6):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {
        "schema_version": "1.0",
        "source_class": "MANUAL_CAPTURE_CURRENT",
        "gw": gw,
        "captured_at": "2026-09-24T17:36:00+07:00",
        "bank": 2,
        "free_transfers": 0,
        "transfer_cost": 0,
        "chips": {
            "wildcard": {"status": "PLAYED", "event": 2},
            "freehit": {"status": "AVAILABLE"},
        },
        "players": [
            {"element_id": i + 1, "position": position}
            for i, position in enumerate(positions)
        ],
    }


def _b64(payload):
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_manual_capture_schema_accepts_current_15_without_inventing_purchase_price():
    row = decode_manual_identity_b64(_b64(_manual_payload()), planning_gw=6)
    assert len(row["players"]) == 15
    assert row["bank"] == 2
    assert row["free_transfers"] == 0
    assert row["availability"]["purchase_price"] == "UNAVAILABLE"


def test_wrong_gw_rejected():
    with pytest.raises(ManualIdentityError, match="planning_gw_mismatch"):
        decode_manual_identity_b64(_b64(_manual_payload(gw=5)), planning_gw=6)


def test_duplicate_player_rejected():
    payload = _manual_payload()
    payload["players"][1]["element_id"] = payload["players"][0]["element_id"]
    with pytest.raises(ManualIdentityError, match="duplicate_or_invalid_element_id"):
        decode_manual_identity_b64(_b64(payload), planning_gw=6)


def test_auth_current_outranks_manual_capture_even_if_manual_is_newer():
    manual = decode_manual_identity_b64(_b64(_manual_payload()), planning_gw=6)
    auth = {
        **manual,
        "generated_at": "2026-09-24T10:00:00+00:00",
        "auth_state": "AUTH_AVAILABLE",
    }
    resolved = select_personal_evidence([
        {
            "source": "auth",
            "source_class": "AUTHENTICATED_CURRENT_TEAM",
            "payload": auth,
            "auth_state": "AUTH_AVAILABLE",
            "gw": 6,
            "observed_at": auth["generated_at"],
        },
        {
            "source": "manual",
            "source_class": "MANUAL_CAPTURE_CURRENT",
            "payload": manual,
            "gw": 6,
            "observed_at": manual["generated_at"],
            "manual_capture_validated": True,
        },
    ], planning_gw=6)
    assert resolved["source"] == "auth"
    assert resolved["resolution_status"] == "CURRENT_VALID"
    assert resolved["stale"] is False


def test_manual_current_outranks_public_previous_deadline():
    manual = decode_manual_identity_b64(_b64(_manual_payload()), planning_gw=6)
    public = {
        "gw": 5,
        "generated_at": "2026-09-18T18:00:00+00:00",
        "picks": [
            {"element_id": i + 101} for i in range(15)
        ],
    }
    resolved = select_personal_evidence([
        {
            "source": "manual",
            "source_class": "MANUAL_CAPTURE_CURRENT",
            "payload": manual,
            "gw": 6,
            "observed_at": manual["generated_at"],
            "manual_capture_validated": True,
        },
        {
            "source": "public",
            "source_class": "OFFICIAL_SUBMITTED_PICKS",
            "payload": public,
            "gw": 5,
            "observed_at": public["generated_at"],
        },
    ], planning_gw=6)
    assert resolved["source"] == "manual"
    assert resolved["finance_allowed"] is True
    assert resolved["stale"] is False


def test_manual_without_validation_marker_cannot_become_current_authority():
    manual = decode_manual_identity_b64(_b64(_manual_payload()), planning_gw=6)
    resolved = select_personal_evidence([
        {
            "source": "manual",
            "source_class": "MANUAL_CAPTURE_CURRENT",
            "payload": manual,
            "gw": 6,
            "observed_at": manual["generated_at"],
        }
    ], planning_gw=6)
    assert resolved["resolution_status"] == "STALE_IDENTITY_FALLBACK"
    assert resolved["stale"] is True


def test_manual_current_authority_is_exactly_second_class_after_auth():
    manual = decode_manual_identity_b64(_b64(_manual_payload()), planning_gw=6)
    resolved = select_personal_evidence([{
        "source": "manual",
        "source_class": "MANUAL_CAPTURE_CURRENT",
        "payload": manual,
        "gw": 6,
        "observed_at": manual["generated_at"],
        "manual_capture_validated": True,
    }], planning_gw=6)
    assert resolved["manual_current"] is True
    assert resolved["authenticated"] is False
    assert resolved["resolution_status"] == "CURRENT_VALID"
    assert resolved["finance_allowed"] is True


def test_name_capture_resolves_only_against_official_universe():
    payload = _manual_payload()
    payload["players"][0].pop("element_id")
    payload["players"][0]["name"] = "Keeper A"
    official = [{"id": 701, "web_name": "Keeper A", "first_name": "A", "second_name": "Keeper"}]
    row = decode_manual_identity_b64(_b64(payload), planning_gw=6, official_players=official)
    assert row["players"][0]["element_id"] == 701
    assert row["players"][0]["captured_name"] == "Keeper A"


def test_name_capture_fails_closed_when_official_name_is_ambiguous():
    payload = _manual_payload()
    payload["players"][0].pop("element_id")
    payload["players"][0]["name"] = "Silva"
    official = [
        {"id": 701, "web_name": "Silva", "first_name": "A", "second_name": "Silva"},
        {"id": 702, "web_name": "Silva", "first_name": "B", "second_name": "Silva"},
    ]
    with pytest.raises(ManualIdentityError, match="name_not_unique_in_official_universe"):
        decode_manual_identity_b64(_b64(payload), planning_gw=6, official_players=official)


def test_name_capture_requires_official_universe():
    payload = _manual_payload()
    payload["players"][0].pop("element_id")
    payload["players"][0]["name"] = "Keeper A"
    with pytest.raises(ManualIdentityError, match="official_player_universe_required"):
        decode_manual_identity_b64(_b64(payload), planning_gw=6)
