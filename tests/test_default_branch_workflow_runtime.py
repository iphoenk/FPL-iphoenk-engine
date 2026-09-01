import json
from pathlib import Path


WORKFLOWS = Path('.github/workflows')
V3_CI_WORKFLOW = WORKFLOWS / 'v3-ci.yml'
V3_RUNTIME_WORKFLOW = WORKFLOWS / 'v3-runtime.yml'
V3_PROVENANCE_POLICY = Path('config/runtime/main_provenance_policy.json')
V4_DEFAULT_BRANCH_WORKFLOWS = (
    'v4-prediction.yml',
    'fpl-engine-recovery.yml',
    'v4-timing-probe.yml',
)
VERSION_EXCLUSIVE_MAIN_WORKFLOWS = (
    '.github/workflows/v4-prediction.yml',
    '.github/workflows/fpl-engine-recovery.yml',
    '.github/workflows/v4-timing-probe.yml',
    '.github/workflows/v5-evidence-dispatcher.yml',
)


def test_v3_ci_main_push_requires_merged_pr_provenance():
    text = V3_CI_WORKFLOW.read_text()
    assert 'pull-requests: read' in text
    assert 'Enforce merged-PR provenance for main' in text
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert 'python -m src.runtime_v3.main_pr_provenance' in text


def test_v3_ci_main_push_ignores_only_version_exclusive_workflows():
    text = V3_CI_WORKFLOW.read_text()
    trigger_block = text.split('permissions:', 1)[0]
    policy = json.loads(V3_PROVENANCE_POLICY.read_text())
    assert 'pull_request:' in trigger_block
    assert 'push:' in trigger_block
    assert set(policy['version_exclusive_paths']) == set(VERSION_EXCLUSIVE_MAIN_WORKFLOWS)
    for path in VERSION_EXCLUSIVE_MAIN_WORKFLOWS:
        assert f"- '{path}'" in trigger_block
    # V3/shared control-plane files must never be excluded from main V3 validation.
    assert "- '.github/workflows/v3-ci.yml'" not in trigger_block
    assert "- '.github/workflows/v3-runtime.yml'" not in trigger_block
    assert "- 'src/**'" not in trigger_block
    assert "- 'config/**'" not in trigger_block


def test_v3_runtime_code_publication_requires_successful_main_ci():
    text = V3_RUNTIME_WORKFLOW.read_text()
    assert 'workflow_run:' in text
    assert 'workflows: ["V3 CI"]' in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert 'Verify source commit passed V3 CI' in text
    assert 'REFUSING_V3_RUNTIME_WITHOUT_GREEN_CI' in text
    assert 'actions: read' in text


def test_v3_runtime_no_longer_directly_triggers_on_main_push():
    text = V3_RUNTIME_WORKFLOW.read_text()
    trigger_block = text.split('permissions:', 1)[0]
    assert '\n  push:\n' not in trigger_block
    assert 'workflow_dispatch:' in trigger_block
    assert 'schedule:' in trigger_block


def test_v3_runtime_publication_provenance_uses_verified_source_commit():
    text = V3_RUNTIME_WORKFLOW.read_text()
    assert "SOURCE_COMMIT: ${{ github.event_name == 'workflow_run' && github.event.workflow_run.head_sha || github.sha }}" in text
    assert 'ref: ${{ env.SOURCE_COMMIT }}' in text
    assert '--source-commit "$SOURCE_COMMIT"' in text
    assert 'if [ "$canonical_main" != "$SOURCE_COMMIT" ]; then' in text
    assert 'python -m src.runtime_v3.version_scope_validate' in text
    assert '--canonical-main "$canonical_main"' in text
    # A main advance is accepted only through the tested scope guard, never by a blind bypass.
    assert 'Refusing stale runtime publication: run_source=' not in text


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
