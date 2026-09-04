from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-hourly-data-ingestion.yml")


def _sections() -> tuple[str, str]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    before_publish, publish = workflow.split("\n  publish:\n", 1)
    return before_publish, publish


def test_v6_acquisition_path_is_read_only_and_cannot_publish():
    before_publish, _ = _sections()

    assert "permissions:\n  contents: read" in before_publish
    assert "persist-credentials: false" in before_publish
    assert "contents: write" not in before_publish
    assert "git push" not in before_publish
    assert "actions/upload-artifact@" in before_publish
    assert "v6-runtime-publication-${{ github.run_id }}-${{ github.run_attempt }}" in before_publish


def test_v6_production_uses_locked_runtime_dependencies_and_lightweight_preflight():
    before_publish, _ = _sections()

    assert "python -m pip install --require-hashes -r requirements.lock" in before_publish
    assert "python -m compileall -q src/runtime_v6" in before_publish
    assert "python -m pytest" not in before_publish
    assert "requirements.txt pytest" not in before_publish


def test_v6_builtin_github_token_remains_read_only_in_publisher_job():
    _, publish = _sections()

    assert "environment: v6-runtime-publisher" in publish
    assert "contents: read" in publish
    # Match the job-level permissions entry exactly enough to avoid treating
    # the GitHub App input `permission-contents: write` as built-in-token write.
    assert "\n      contents: write\n" not in publish
    assert "actions: read" in publish
    assert "actions/download-artifact@" in publish
    assert "Revalidate transferred runtime snapshot" in publish


def test_v6_has_fail_closed_dedicated_publisher_app_contract_without_cross_version_secret_reuse():
    _, publish = _sections()

    assert "Require dedicated V6 publisher app configuration" in publish
    assert "actions/create-github-app-token@" in publish
    assert "V6_RUNTIME_APP_ID" in publish
    assert "V6_RUNTIME_APP_PRIVATE_KEY" in publish
    assert "permission-contents: write" in publish
    assert "dedicated_v6_github_app" in publish
    assert "scoped_github_token_fallback" not in publish
    assert "V3_RUNTIME_APP_ID" not in publish
    assert "V3_RUNTIME_APP_PRIVATE_KEY" not in publish
    assert "V4_RUNTIME_APP_ID" not in publish
    assert "V4_RUNTIME_APP_PRIVATE_KEY" not in publish
    assert "steps.runtime_app_token.outputs.token || github.token" not in publish
    assert "token: ${{ steps.runtime_app_token.outputs.token }}" in publish
    assert "PUBLISH_TOKEN: ${{ steps.runtime_app_token.outputs.token }}" in publish
    assert "persist-credentials: false" in publish


def test_v6_publisher_uses_atomic_orphan_snapshot_with_lease():
    _, publish = _sections()

    assert "git checkout --orphan runtime-snapshot" in publish
    assert '--force-with-lease="refs/heads/${RUNTIME_BRANCH}:${RUNTIME_BASE_SHA}"' in publish
    assert 'origin "HEAD:refs/heads/${RUNTIME_BRANCH}"' in publish
    assert "git add -f data/v6" in publish
    assert "grep -v '^data/v6/'" in publish
    assert "diff -qr" in publish
    assert 'http.https://github.com/.extraheader="AUTHORIZATION: basic $basic_auth"' in publish


def test_v6_publisher_reverifies_governance_after_artifact_transfer():
    _, publish = _sections()

    assert 'manifest["governance"]["data_only"] is True' in publish
    assert 'manifest["governance"]["decision_authority"] == "NONE"' in publish
    assert 'manifest["governance"]["prediction_authority"] == "NONE"' in publish
    assert 'manifest["governance"]["optimizer_authority"] == "NONE"' in publish
    assert 'integrity["status"] == "PASS"' in publish
    assert 'integrity["resolved_registry_exact"] is True' in publish
