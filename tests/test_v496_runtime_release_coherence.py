from __future__ import annotations

import json
from pathlib import Path


def test_prediction_runtime_identity_matches_canonical_release() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config" / "release_manifest.json").read_text())
    prediction_source = (root / "src" / "services" / "prediction_service.py").read_text()
    health_source = (root / "src" / "engines" / "framework_health_audit.py").read_text()
    quality_gate_source = (root / "src" / "engines" / "v4_quality_gate.py").read_text()
    quality_gate_legacy = (root / "src" / "engines" / "v4_quality_gate_legacy.py").read_text()
    docs = (root / "docs" / "v4-microservices.md").read_text()
    readme = (root / "README.md").read_text()
    release = manifest["release"]
    schema = int(release.replace(".", ""))

    assert f'"schema_version": {schema}' in prediction_source
    assert f'"engine_version": "{release}-official-first-reporting"' in prediction_source
    assert "from src.release import RELEASE_VERSION" in health_source
    assert '"engine": f"v{RELEASE_VERSION}-truthful-health"' in health_source
    assert '"engine": "v4.9.2-truthful-health"' not in health_source
    assert "from src.engines import v4_quality_gate_legacy as legacy" in quality_gate_source
    assert '_assert_version(obj, phase, 492, f"v{RELEASE_VERSION}-truthful-health")' in quality_gate_legacy
    assert docs.startswith(f"# V{release} service architecture")
    assert readme.startswith(f"# FPL iphoenk Engine V{release}")
    assert manifest["canonical_branch"] == "v4-prediction-engine"
    assert manifest["runtime_branch"] == "runtime-data-v4"
    assert manifest["required_check"] == "core / validate-v4"
    assert manifest["status"] == "CANONICAL_PRODUCTION_GREEN"
