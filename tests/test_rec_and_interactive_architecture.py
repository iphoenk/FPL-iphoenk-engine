import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_rec_registry_is_single_canonical_set_and_projections_match():
    rec = _load("config/rec_registry.json")
    impl = _load("IMPLEMENTATION_STATUS.json")
    official = _load("config/sources/official_first_coverage.json")
    rows = rec["records"]
    ids = [row["id"] for row in rows]
    assert rec["registry"] == "V3_REC_REGISTRY_V1"
    assert len(ids) == rec["expected_count"]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(impl["rec_status"]) == set(official["recommendations"])
    for row in rows:
        assert row["status"] == impl["rec_status"][row["id"]]["status"]
        assert row["relation"] in rec["allowed_relations"]


def test_interactive_lane_is_bounded_and_uses_canonical_slo_authority():
    background = _load("config/v3_service_registry.json")["services"]
    interactive = _load("config/runtime/interactive_service_registry.json")
    instant = _load("config/runtime/instant_serving.json")
    slo = _load("config/runtime/performance_slo.json")
    ownership = _load("config/v3_architecture_ownership_registry.json")
    services = interactive["services"]
    assert interactive["registry"] == "V3_INTERACTIVE_SERVICES_V1"
    assert set(services) == {"unified_fastpath"}
    assert not (set(background) & set(services))
    assert all(spec["network"] is False for spec in services.values())
    assert all(spec["writes_canonical_artifacts"] is False for spec in services.values())
    assert interactive["policy"]["performance_slo_registry"] == "config/runtime/performance_slo.json"
    assert interactive["policy"]["performance_slo_profile"] == "instant_serving"
    assert instant["performance"]["slo_registry"] == "config/runtime/performance_slo.json"
    assert instant["performance"]["slo_profile"] == "instant_serving"
    canonical = slo["profiles"]["instant_serving"]
    assert canonical["target_wall_ms"] == 500
    assert canonical["legacy_ceiling_ms"] == 1000
    assert interactive["policy"]["single_pass_artifact_load_and_validation"] is True
    responsibilities = {row["id"]: row for row in ownership["responsibilities"]}
    assert responsibilities["INTERACTIVE_DECISION_REGENERATION"]["owner_service"] == "unified_fastpath"
    assert responsibilities["INTERACTIVE_VALIDATED_GATEWAY"]["owner_service"] == "unified_fastpath"
    assert set(interactive["compatibility_entrypoints"]) == {"decision_hotpath", "instant_gateway"}


def test_unified_fastpath_consumes_canonical_governance_builders_not_duplicate_formulas():
    text = (ROOT / "src/runtime_v3/unified_fastpath.py").read_text(encoding="utf-8")
    assert "from src.engines.lineup_governance import build_lineup_decision, build_package_decision" in text
    assert "from src.sources.official_fpl" not in text
    assert "get_json(" not in text
    assert "def build_lineup_decision" not in text
    assert "def build_package_decision" not in text
