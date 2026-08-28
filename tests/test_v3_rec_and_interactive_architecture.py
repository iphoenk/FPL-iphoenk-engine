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
    assert len(ids) == rec["expected_count"] == 43
    assert len(ids) == len(set(ids))
    assert set(ids) == set(impl["rec_status"]) == set(official["recommendations"])
    for row in rows:
        assert row["status"] == impl["rec_status"][row["id"]]["status"]
        assert row["relation"] in rec["allowed_relations"]


def test_interactive_lane_is_bounded_and_does_not_duplicate_business_owners():
    background = _load("config/v3_service_registry.json")["services"]
    interactive = _load("config/runtime/interactive_service_registry.json")
    ownership = _load("config/v3_architecture_ownership_registry.json")
    services = interactive["services"]
    assert interactive["registry"] == "V3_INTERACTIVE_SERVICES_V1"
    assert set(services) == {"decision_hotpath", "instant_gateway"}
    assert not (set(background) & set(services))
    assert all(spec["network"] is False for spec in services.values())
    assert all(spec["writes_canonical_artifacts"] is False for spec in services.values())
    assert interactive["policy"]["hard_end_to_end_ceiling_ms"] == 1000
    responsibilities = {row["id"]: row for row in ownership["responsibilities"]}
    assert responsibilities["INTERACTIVE_DECISION_REGENERATION"]["owner_service"] == "decision_hotpath"
    assert responsibilities["INTERACTIVE_VALIDATED_GATEWAY"]["owner_service"] == "instant_gateway"


def test_hotpath_consumes_canonical_governance_builders_not_duplicate_formulas():
    text = (ROOT / "src/engines/decision_hotpath_service.py").read_text(encoding="utf-8")
    assert "from src.engines.lineup_governance import build_lineup_decision, build_package_decision" in text
    assert "from src.sources.official_fpl" not in text
    assert "get_json(" not in text
    assert "def build_lineup_decision" not in text
    assert "def build_package_decision" not in text
