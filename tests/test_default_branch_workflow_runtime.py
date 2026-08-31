from pathlib import Path


WORKFLOWS = Path('.github/workflows')
V4_DEFAULT_BRANCH_WORKFLOWS = (
    'v4-prediction.yml',
    'fpl-engine-recovery.yml',
    'v4-timing-probe.yml',
)


def test_default_branch_v4_workflows_use_node24_compatible_actions():
    combined = '\n'.join((WORKFLOWS / name).read_text() for name in V4_DEFAULT_BRANCH_WORKFLOWS)
    assert 'actions/checkout@v4' not in combined
    assert 'actions/setup-python@v5' not in combined
    assert 'actions/upload-artifact@v4' not in combined
    assert 'actions/checkout@v7' in combined
    assert 'actions/setup-python@v7' in combined
    assert 'actions/upload-artifact@v7' in combined


def test_default_branch_v4_publishers_keep_shared_non_cancelling_lock():
    for name in V4_DEFAULT_BRANCH_WORKFLOWS:
        text = (WORKFLOWS / name).read_text()
        assert 'group: fpl-iphoenk-v4-gate' in text, name
        assert 'cancel-in-progress: false' in text, name
