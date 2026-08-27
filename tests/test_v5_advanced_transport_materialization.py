from __future__ import annotations

import json
from pathlib import Path

import msgpack

from src.v5 import service_client
from src.v5.services import snapshot as snapshot_service

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class BinaryResponse:
    status_code = 200

    def __init__(self, envelope: dict):
        self.content = msgpack.packb(envelope, use_bin_type=True)

    def raise_for_status(self) -> None:
        return None


def test_wire_profiles_are_registry_driven_and_keep_json_compatibility():
    cfg = _load("config/v5_service_wire_registry.json")
    profiles = cfg["profiles"]
    assert cfg["default_profile"] in profiles
    assert profiles["json_compat"]["codec"] == "json"
    assert profiles["advanced_binary"]["codec"] == "msgpack"
    assert profiles["json_compat"]["invoke_path"] != profiles["advanced_binary"]["invoke_path"]
    assert cfg["governance"]["service_boundaries_remain_independent"] is True
    assert cfg["governance"]["business_authority_unchanged_by_codec"] is True


def test_msgpack_client_round_trip_preserves_contract_and_observability(monkeypatch):
    captured = {}

    def fake_post_bytes(service_id, operation, url, *, body, headers, timeout):
        captured.update(
            {
                "service_id": service_id,
                "operation": operation,
                "url": url,
                "body": msgpack.unpackb(body, raw=False, strict_map_key=False),
                "headers": headers,
                "timeout": timeout,
            }
        )
        envelope = {
            "ok": True,
            "contract_version": "v1",
            "service_id": service_id,
            "operation": operation,
            "elapsed_ms": 1.25,
            "data": {"nested": {"values": [1, 2, 3]}},
        }
        return BinaryResponse(envelope), 1, {"state": "CLOSED", "failures": 0}

    monkeypatch.setenv("V5_INTERNAL_WIRE_PROFILE", "advanced_binary")
    monkeypatch.setattr(service_client, "transport_post_bytes", fake_post_bytes)
    result = service_client.invoke_envelope(
        "prediction",
        "build",
        {"nested": {"values": [1, 2, 3]}},
        correlation_id="binary-contract-test",
    )

    assert captured["url"].endswith("/v1/invoke-bin/build")
    assert captured["headers"]["Content-Type"] == "application/msgpack"
    assert captured["body"]["_contract_version"] == "v1"
    assert captured["body"]["_correlation_id"] == "binary-contract-test"
    assert result["data"]["nested"]["values"] == [1, 2, 3]
    assert result["transport_codec"] == "msgpack"
    assert result["transport_profile"] == "advanced_binary"


def test_snapshot_materialization_is_durable_first_and_avoids_readback(monkeypatch, tmp_path):
    writes = []
    reads = []
    snapshot_service.reset_materialization_for_tests()

    def fake_write(name, data):
        writes.append((name, data))
        return tmp_path / f"{name}.json"

    def fake_read(name, default=None):
        reads.append(name)
        return default

    monkeypatch.setattr(snapshot_service, "write_artifact", fake_write)
    monkeypatch.setattr(snapshot_service, "read_artifact", fake_read)

    payload = {"players": [{"element": 1, "xpts_5": 25.0}]}
    result = snapshot_service.handle("write", {"name": "predictions", "data": payload})
    cached = snapshot_service.handle("read", {"name": "predictions", "default": {}})
    status = snapshot_service.handle("materialization_status", {})

    assert writes == [("predictions", payload)]
    assert result["materialized"] is True
    assert cached == payload
    assert reads == []
    assert status["hits"] == 1
    assert status["durable_store_authoritative"] is True


def test_unregistered_runtime_artifact_falls_back_to_durable_store(monkeypatch):
    snapshot_service.reset_materialization_for_tests()
    calls = []

    def fake_read(name, default=None):
        calls.append(name)
        return {"source": "durable"}

    monkeypatch.setattr(snapshot_service, "read_artifact", fake_read)
    result = snapshot_service.handle("read", {"name": "technical_appendix", "default": {}})
    assert result == {"source": "durable"}
    assert calls == ["technical_appendix"]


def test_advanced_deployment_preserves_independent_service_boundaries():
    compose = (ROOT / "deploy/v5/docker-compose.yml").read_text(encoding="utf-8")
    client_source = (ROOT / "src/v5/service_client.py").read_text(encoding="utf-8")
    host_source = (ROOT / "src/v5/service_host.py").read_text(encoding="utf-8")

    assert "V5_INTERNAL_WIRE_PROFILE" in compose
    assert "advanced_binary" in compose
    assert "src.v5.services." not in client_source
    assert "invoke_binary" in host_source
    assert "msgpack.unpackb" in host_source
