from pathlib import Path


def test_exhaustive_finalizer_module_is_declared_and_canonical():
    source = Path("src/engines/package_optimizer_exhaustive_finalize.py").read_text(encoding="utf-8")
    assert "score_package(" in source
    assert '"search_authority": "FULL"' in source
    assert '"lossy_pruning": False' in source
    assert "build_package_decision" in source
    assert "safe_per_gw_dominates" in source
