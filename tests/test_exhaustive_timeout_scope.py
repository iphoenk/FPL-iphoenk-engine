from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_exhaustive_timeout_is_profile_scoped_not_global():
    service_registry = _json("config/v3_service_registry.json")
    profiles = _json("config/runtime/execution_profiles.json")["profiles"]
    orchestrator = (ROOT / "src/runtime_v3/domain_orchestrator.py").read_text(encoding="utf-8")

    assert service_registry["runtime"]["service_timeout_seconds"] == 180
    assert profiles["exhaustive_precompute"]["service_timeout_seconds"] == 300
    for profile in ("fast_decision", "live", "full_refresh", "deep_stats"):
        assert "service_timeout_seconds" not in profiles[profile]

    assert 'profile_cfg.get("service_timeout_seconds")' in orchestrator
