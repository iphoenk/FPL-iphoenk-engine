from pathlib import Path


WORKFLOWS = Path('.github/workflows')
PUBLISHERS = (
    'fpl-engine.yml',
    'fpl-engine-recovery.yml',
    'deep-stats.yml',
)
SHARED_GROUP = 'fpl-iphoenk-v4-gate'


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

    # Canonical recovery is a non-scheduled compatibility wrapper only. The
    # default branch owns runtime hydration/freshness detection before it calls
    # this branch's reusable core.
    assert 'schedule:' not in recovery
    assert 'cron:' not in recovery
    assert 'uses: ./.github/workflows/fpl-engine-core.yml' in recovery


def test_every_runtime_publisher_shares_one_non_cancelling_production_domain():
    gate = (WORKFLOWS / 'fpl-engine.yml').read_text()
    recovery = (WORKFLOWS / 'fpl-engine-recovery.yml').read_text()
    deep_stats = (WORKFLOWS / 'deep-stats.yml').read_text()

    # Production push/manual publication, recovery and deep-stats all serialize
    # on the production lock and never cancel one another.
    assert f"|| '{SHARED_GROUP}'" in gate
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in gate
    for name, text in (('fpl-engine-recovery.yml', recovery), ('deep-stats.yml', deep_stats)):
        assert f'group: {SHARED_GROUP}' in text, name
        assert 'cancel-in-progress: false' in text, name
        assert 'publish: true' in text, name

    # PR validation must not share the production lock: it can supersede only
    # an older validation run for the same PR.
    assert 'fpl-iphoenk-v4-pr-{0}' in gate
    assert "format('fpl-iphoenk-v4-pr-{0}', github.event.pull_request.number)" in gate


def test_canonical_branch_has_no_second_scheduled_timing_owner():
    assert not (WORKFLOWS / 'fpl-engine-timing-probe.yml').exists()
    recovery = (WORKFLOWS / 'fpl-engine-recovery.yml').read_text()
    assert 'schedule:' not in recovery
    assert 'cron:' not in recovery
