from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v5-shadow-cycle.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_shadow_cycle_binds_to_deployed_runtime_and_allows_main_to_be_ahead() -> None:
    text = _text()

    assert 'git merge-base --is-ancestor "$V3_SOURCE_SHA" "origin/$V3_SOURCE_BRANCH"' in text
    assert 'test "$(git rev-parse origin/$V3_SOURCE_BRANCH)" = "$V3_SOURCE_SHA"' not in text
    assert "runtime-data source_commit drift" in text
    assert "Repository main is ahead of deployed production" in text


def test_shadow_analytics_storage_policy_is_derived_from_persistence_registry() -> None:
    text = _text()

    assert "config/v5_persistence_registry.json" in text
    assert "history_retention = (persistence.get('write_policy') or {}).get('history_retention') or {}" in text
    assert "'rolling_history_canonical': bool(storage_cfg.get('history_jsonl_is_canonical', False))" in text
    assert "'rolling_history_max_bytes': int(history_retention.get('max_bytes') or 0)" in text
