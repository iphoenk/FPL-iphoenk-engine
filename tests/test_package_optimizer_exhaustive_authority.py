from pathlib import Path


def test_full_search_authority_is_not_a_config_only_label():
    text = Path("src/engines/package_optimizer_exhaustive_finalize.py").read_text(encoding="utf-8")
    assert '"single_budget_applied": False' in text
    assert '"pair_budget_applied": False' in text
    assert '"exact_package_limit_applied": False' in text
    assert "canonical_score_package_reused_for_every_legal_package" in text
