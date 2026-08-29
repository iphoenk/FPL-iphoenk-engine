from pathlib import Path


WORKFLOWS = Path('.github/workflows')
PUBLISHERS = (
    'fpl-engine.yml',
    'fpl-engine-recovery.yml',
    'fpl-engine-timing-probe.yml',
    'deep-stats.yml',
)
SHARED_GROUP = 'group: fpl-iphoenk-v4-gate'


def test_v4_workflows_never_push_generated_data_to_protected_canonical_branch():
    offenders = []
    for name in ('fpl-engine-core.yml', *PUBLISHERS):
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


def test_every_runtime_publisher_shares_one_non_cancelling_concurrency_domain():
    for name in PUBLISHERS:
        text = (WORKFLOWS / name).read_text()
        assert 'publish: true' in text or "publish: ${{ github.event_name != 'pull_request' }}" in text, name
        assert SHARED_GROUP in text, name

    # A publishing timing-probe/deep-stats run must queue behind an in-flight
    # canonical/recovery publication instead of cancelling it.
    for name in ('fpl-engine-timing-probe.yml', 'deep-stats.yml'):
        text = (WORKFLOWS / name).read_text()
        publishing_job = text.split('uses: ./.github/workflows/fpl-engine-core.yml', 1)[0]
        assert SHARED_GROUP in publishing_job, name
        assert 'cancel-in-progress: false' in publishing_job, name
