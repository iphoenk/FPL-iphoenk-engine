from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V6_CI = ROOT / ".github" / "workflows" / "v6-ci.yml"
REPO_GOV = ROOT / ".github" / "workflows" / "repository-governance.yml"


def test_v6_ci_path_filter_covers_every_v6_workflow_generically():
    text = V6_CI.read_text(encoding="utf-8")
    assert '.github/workflows/v6-*.yml' in text


def test_repository_governance_detects_every_v6_workflow_generically():
    text = REPO_GOV.read_text(encoding="utf-8")
    assert r'\.github/workflows/v6-.*\.yml$' in text
