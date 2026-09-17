from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-wave3-proof.yml")


def test_wave3_observer_paginates_repository_artifacts_before_filtering_proofs():
    text = WORKFLOW.read_text(encoding="utf-8")
    command = 'gh api --paginate --slurp "/repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100"'
    assert text.count(command) == 2
    assert text.count("pages = payload if isinstance(payload, list) else [payload]") == 2
    assert text.count("for page in pages:") == 2


def test_wave3_observer_does_not_regress_to_first_page_only_artifact_lookup():
    text = WORKFLOW.read_text(encoding="utf-8")
    first_page_only = 'gh api "/repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100"'
    assert first_page_only not in text
