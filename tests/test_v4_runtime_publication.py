from pathlib import Path


WORKFLOWS = Path('.github/workflows')


def test_v4_workflows_never_push_generated_data_to_protected_canonical_branch():
    offenders = []
    for name in ('fpl-engine-core.yml', 'deep-stats.yml', 'fpl-engine-recovery.yml'):
        text = (WORKFLOWS / name).read_text()
        if 'git push origin HEAD:v4-prediction-engine' in text:
            offenders.append(name)
    assert offenders == []


def test_v4_runtime_state_uses_dedicated_branch_and_atomic_snapshot():
    core = (WORKFLOWS / 'fpl-engine-core.yml').read_text()
    recovery = (WORKFLOWS / 'fpl-engine-recovery.yml').read_text()

    assert 'RUNTIME_BRANCH: runtime-data-v4' in core
    assert 'git checkout --orphan runtime-snapshot' in core
    assert 'git push --force origin HEAD:"$RUNTIME_BRANCH"' in core
    assert 'Verify published V4 runtime snapshot' in core

    assert 'RUNTIME_BRANCH: runtime-data-v4' in recovery
    assert 'origin/${RUNTIME_BRANCH}:data/latest.json' in recovery
