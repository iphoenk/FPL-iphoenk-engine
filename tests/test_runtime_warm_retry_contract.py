import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v3-runtime.yml"


def test_fast_runtime_retry_is_bounded_and_keeps_hard_slo():
    text = WORKFLOW.read_text(encoding="utf-8")
    slo = json.loads((ROOT / "config/runtime/performance_slo.json").read_text(encoding="utf-8"))
    fast = slo["profiles"]["fast_decision"]

    assert "Enforce selected profile runtime SLO with one bounded warm retry" in text
    assert text.count("FAST_SLO_WARM_RETRY") == 1
    assert 'if [ "$profile" != "fast_decision" ]; then' in text
    assert "retrying exactly once" in text
    assert text.count("python -m src.runtime_v3.performance_guard --profile") == 2
    assert fast["target_wall_ms"] == 3000
    assert fast["legacy_ceiling_ms"] == 3000
    assert fast["enforcement"] == "HARD_CEILING"


def test_warm_retry_revalidates_production_contracts_before_publication():
    text = WORKFLOW.read_text(encoding="utf-8")
    retry = text.index("FAST_SLO_WARM_RETRY")
    publish = text.index("Materialize and validate publication whitelist")
    segment = text[retry:publish]

    for command in (
        "src.engines.source_contract_validate",
        "src.engines.production_contract_validate",
        "src.engines.watchlist_contract_validate",
        "src.engines.report_serving_validate",
        "src.engines.report_time_contract_validate",
    ):
        assert command in segment
    assert "src.runtime_v3.domain_orchestrator" in segment
