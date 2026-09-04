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


def test_v6_write_authority_is_isolated_to_publisher_job():
    _, publish = _sections()

    assert "environment: v6-runtime-publisher" in publish
    assert "contents: write" in publish
    assert "actions: read" in publish
    assert "actions/download-artifact@" in publish
    assert "Revalidate transferred runtime snapshot" in publish


def test_v6_has_dedicated_publisher_app_contract_without_cross_version_secret_reuse():
    _, publish = _sections()

    assert "actions/create-github-app-token@" in publish
    assert "V6_RUNTIME_APP_ID" in publish
    assert "V6_RUNTIME_APP_PRIVATE_KEY" in publish
    assert "dedicated_v6_github_app" in publish
    assert "scoped_github_token_fallback" in publish
    assert "V3_RUNTIME_APP_ID" not in publish
    assert "V3_RUNTIME_APP_PRIVATE_KEY" not in publish
    assert "V4_RUNTIME_APP_ID" not in publish
    assert "V4_RUNTIME_APP_PRIVATE_KEY" not in publish
    assert "steps.runtime_app_token.outputs.token || github.token" in publish
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
