from src.runtime_v3 import domain_process_runner as runner


def test_invalid_ttl_reuse_is_rejected_as_cache_miss():
    def invalid_loader(service_name, spec, data, profile_cfg):
        raise RuntimeError("artifact fixture_weather.json missing required field evidence_precedence")

    reused, rejected = runner._reuse_candidate(
        "TTL",
        invalid_loader,
        "source_layer",
        {"artifacts": ["fixture_weather.json"]},
        "fast_decision",
        {"reuse_services": {"source_layer": {"max_age_seconds": 180}}},
    )

    assert reused is None
    assert rejected["mode"] == "TTL"
    assert rejected["reason"] == "ARTIFACT_CONTRACT_REJECTED"
    assert "evidence_precedence" in rejected["error"]


def test_invalid_reuse_falls_through_to_owner_refresh(monkeypatch):
    monkeypatch.setattr(runner.incremental_reuse, "active", lambda profile, service=None: False)
    monkeypatch.setattr(runner.incremental_reuse, "_registry", lambda: {"services": {}})
    monkeypatch.setattr(
        runner.reuse_freshness,
        "reuse_service",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("old weather schema")),
    )
    monkeypatch.setattr(runner.module_batch_runner, "_registry", lambda: {"batches": {}})
    monkeypatch.setattr(runner.legacy, "_validate_service_outputs", lambda *args, **kwargs: [])

    result = runner._run_service(
        "source_layer",
        {"commands": [], "artifacts": []},
        {},
        "fast_decision",
        {"reuse_services": {"source_layer": {"max_age_seconds": 180}}},
    )

    assert result["status"] == "SUCCESS"
    assert result["reuse_rejections"] == [
        {
            "mode": "TTL",
            "reason": "ARTIFACT_CONTRACT_REJECTED",
            "error": "RuntimeError: old weather schema",
        }
    ]


def test_valid_reuse_remains_accepted():
    expected = {"service": "source_layer", "status": "REUSED"}

    reused, rejected = runner._reuse_candidate(
        "TTL",
        lambda *args, **kwargs: expected,
        "source_layer",
        {"artifacts": ["fixture_weather.json"]},
        "fast_decision",
        {"reuse_services": {"source_layer": {"max_age_seconds": 180}}},
    )

    assert reused is expected
    assert rejected is None
