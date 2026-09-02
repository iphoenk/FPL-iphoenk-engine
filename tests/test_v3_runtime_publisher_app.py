from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_WORKFLOW = ROOT / ".github" / "workflows" / "v3-runtime.yml"
GOVERNANCE_WORKFLOW = ROOT / ".github" / "workflows" / "v3-platform-governance.yml"


def test_v3_runtime_publisher_uses_dedicated_github_app_token() -> None:
    text = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    publish = text.split("\n  publish:\n", 1)[1]

    assert "Mint governed V3 runtime publisher token" in publish
    assert "actions/create-github-app-token@fee1f7d63c2ff003460e3d139729b119787bc349" in publish
    assert "app-id: ${{ vars.V3_RUNTIME_APP_ID }}" in publish
    assert "private-key: ${{ secrets.V3_RUNTIME_APP_PRIVATE_KEY }}" in publish
    assert "permission-contents: write" in publish
    assert "GH_TOKEN: ${{ steps.runtime_app_token.outputs.token }}" in publish
    assert '--force-with-lease="refs/heads/${RUNTIME_BRANCH}:${RUNTIME_BASE_SHA}"' in publish


def test_v3_publish_job_does_not_grant_generic_github_token_write() -> None:
    text = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    publish = text.split("\n  publish:\n", 1)[1]
    permissions = publish.split("    runs-on:", 1)[0]

    assert "contents: read" in permissions
    assert "actions: read" in permissions
    assert "contents: write" not in permissions

    atomic = publish.split("- name: Publish rolling runtime snapshot atomically", 1)[1]
    atomic = atomic.split("- name: Verify published runtime provenance", 1)[0]
    assert "GH_TOKEN: ${{ steps.runtime_app_token.outputs.token }}" in atomic
    assert "GH_TOKEN: ${{ github.token }}" not in atomic


def test_platform_governance_binds_exact_publisher_app_id_variable() -> None:
    text = GOVERNANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "V3_RUNTIME_PUBLISHER_APP_ID: ${{ vars.V3_RUNTIME_APP_ID }}" in text
