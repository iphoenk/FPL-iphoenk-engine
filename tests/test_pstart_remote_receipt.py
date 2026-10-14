import hashlib
import json
from pathlib import Path

import pytest

from src.engines import v12_pstart_remote_receipt as verify


def _snapshot():
    rows = [
        {"element": 11, "position": "GK", "baseline": {"start_probability": 0.75},
         "individualized": {"start_probability": 0.8}},
        {"element": 12, "position": "MID", "baseline": {"start_probability": 0.65},
         "individualized": {"start_probability": 0.7}},
    ]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    a = b'{"a":"raw official"}'
    b = b'{"a":"normalized official"}'
    payload = {
        "contract": "V12_PSTART_PROSPECTIVE_PREDEADLINE_V1",
        "model_sha": "a" * 40,
        "report_slot": "2026-10-14T12:30:00+07:00",
        "planning_gw": 7,
        "captured_at": "2026-10-14T05:39:38+00:00",
        "official_deadline": "2026-10-17T10:00:00+00:00",
        "universe_expected": 2,
        "universe_observed": 2,
        "forecast_rows": rows,
        "forecast_rows_sha256": digest,
        "source": {
            "id": "official_fpl",
            "source_file_sha256": {
                "data/v6/current/official_fpl.json": hashlib.sha256(a).hexdigest(),
                "data/v6/normalized/sources/official_fpl.json": hashlib.sha256(b).hexdigest(),
            },
        },
    }
    bytes_value = json.dumps(payload).encode()
    receipt = {
        "pstart_prospective_sha256": hashlib.sha256(bytes_value).hexdigest(),
        "model_sha": "a" * 40, "runtime_sha": "b" * 40,
        "report_slot": payload["report_slot"], "planning_gw": 7,
    }
    objects = {
        ("c" * 40, "reports/test/pstart_predeadline_forecast.json"): bytes_value,
        ("b" * 40, "data/v6/current/official_fpl.json"): a,
        ("b" * 40, "data/v6/normalized/sources/official_fpl.json"): b,
    }
    return receipt, objects


def _accept(monkeypatch, receipt, objects):
    monkeypatch.setattr(
        verify, "_object", lambda root, rev, path: objects[(rev, path)]
    )
    return verify.verify_forecast(
        receipt,
        private_repo=Path("private"),
        private_commit="c" * 40,
        occurrence_path="reports/test",
        runtime_repo=Path("runtime"),
    )


def test_remote_forecast_and_original_v6_bytes_pass(monkeypatch):
    receipt, objects = _snapshot()
    result = _accept(monkeypatch, receipt, objects)
    assert result["pstart_prospective_remote_readback"] == "PASS"
    assert result["pstart_prospective_source_sha256_readback"] == "PASS"
    assert result["pstart_prospective_private_commit"] == "c" * 40


def test_private_forecast_digest_corruption_fails_closed(monkeypatch):
    receipt, objects = _snapshot()
    objects[("c" * 40, "reports/test/pstart_predeadline_forecast.json")] += b"\n"
    with pytest.raises(verify.ForecastReadbackError, match="PRIVATE_FORECAST_SHA256_MISMATCH"):
        _accept(monkeypatch, receipt, objects)


def test_original_v6_digest_corruption_fails_closed(monkeypatch):
    receipt, objects = _snapshot()
    objects[("b" * 40, "data/v6/current/official_fpl.json")] += b"tamper"
    with pytest.raises(verify.ForecastReadbackError, match="ORIGINAL_V6_BLOB_SHA256_MISMATCH"):
        _accept(monkeypatch, receipt, objects)


def test_forged_postdeadline_snapshot_fails_closed(monkeypatch):
    receipt, objects = _snapshot()
    payload = json.loads(objects[("c" * 40, "reports/test/pstart_predeadline_forecast.json")])
    payload["captured_at"] = "2026-10-19T00:00:00+00:00"
    raw = json.dumps(payload).encode()
    objects[("c" * 40, "reports/test/pstart_predeadline_forecast.json")] = raw
    receipt["pstart_prospective_sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(verify.ForecastReadbackError, match="NOT_GENUINE_PREDEADLINE"):
        _accept(monkeypatch, receipt, objects)


def test_forecast_without_capture_does_not_claim_pass():
    assert verify.verify_forecast(
        {}, private_repo=Path("private"), private_commit="c" * 40,
        occurrence_path="reports/test", runtime_repo=Path("runtime"),
    )["pstart_prospective_remote_readback"] == "NOT_APPLICABLE"
