import re
from pathlib import Path


WORKFLOW = Path('.github/workflows/fpl-engine-core.yml')


def test_runtime_publication_is_single_atomic_mutation():
    text = WORKFLOW.read_text()
    assert text.count('git push --force origin HEAD:"$RUNTIME_BRANCH"') == 1
    assert 'Publish complete runtime snapshot atomically' in text
    assert 'Publish core branch data' not in text
    assert 'Publish ablation diagnostic data' not in text


def test_ablation_is_observational_not_runtime_authority():
    text = WORKFLOW.read_text()
    assert 'continue-on-error: true' in text
    assert 'failure_cannot_block_core_publish' in text
    assert 'observational_outside_decision_chain' in text


def test_core_actions_use_node24_compatible_majors():
    text = WORKFLOW.read_text()
    required = ('actions/checkout', 'actions/setup-python', 'actions/upload-artifact')
    for action in required:
        rows = [line.strip() for line in text.splitlines() if f'uses: {action}@' in line]
        assert rows, action
        assert all(re.search(r'#\s*v7\s*$', row) for row in rows), (action, rows)
    assert 'actions/checkout@v4' not in text
    assert 'actions/setup-python@v5' not in text
    assert 'actions/upload-artifact@v4' not in text


def test_publish_path_is_bound_to_current_canonical_v4():
    text = WORKFLOW.read_text()
    guard = 'Assert publish ref is current canonical V4'
    canonical_lookup = 'git ls-remote origin refs/heads/v4-prediction-engine'
    checked_out = 'checked_out_sha="$(git rev-parse HEAD)"'
    mismatch = 'publish ref $checked_out_sha is not current canonical V4 $canonical_sha'
    assert text.count(guard) == 2
    assert text.count(canonical_lookup) == 2
    assert text.count(checked_out) == 2
    assert text.count(mismatch) == 2
    assert text.rfind(guard) < text.index('Publish complete runtime snapshot atomically')
