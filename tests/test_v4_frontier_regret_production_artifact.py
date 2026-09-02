from __future__ import annotations

import v4_frontier_regret_shadow as shadow


def test_audit_current_runtime_uses_canonical_wc_package_artifact(monkeypatch):
    production = {"marker": "canonical-wc-package-audit"}
    seen = {}

    def fake_read(path, default):
        if path == shadow.SHADOW_CONFIG:
            return {"enabled": True}
        if path == shadow.PRODUCTION_PACKAGE_ARTIFACT:
            return production
        return {}

    monkeypatch.setattr(shadow, "read_json", fake_read)
    monkeypatch.setattr(shadow, "build_candidates", lambda predictions, universe: [])

    def fake_shadow(candidates, locked, **kwargs):
        seen["production_artifact"] = kwargs["production_artifact"]
        return {"status": "TEST"}

    monkeypatch.setattr(shadow, "frontier_regret_shadow_from_candidates", fake_shadow)

    out = shadow.audit_current_runtime()

    assert shadow.PRODUCTION_PACKAGE_ARTIFACT.name == "wc_package_audit_v4.json"
    assert seen["production_artifact"] is production
    assert out["status"] == "TEST"
