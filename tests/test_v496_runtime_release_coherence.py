from __future__ import annotations

import json
from pathlib import Path


def test_prediction_runtime_identity_matches_canonical_release() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config" / "release_manifest.json").read_text())
    source = (root / "src" / "services" / "prediction_service.py").read_text()
    release = manifest["release"]
    schema = int(release.replace(".", ""))
    assert f'"schema_version": {schema}' in source
    assert f'"engine_version": "{release}-official-first-reporting"' in source
