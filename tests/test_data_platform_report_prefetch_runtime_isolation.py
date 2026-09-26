from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-natural-data-ingestion.yml")


def test_v6_production_checkout_is_shallow_and_never_fetches_other_engine_branches():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" not in workflow
    # Three public-repository checkouts exist by design: read-only acquisition,
    # isolated public publisher, and isolated private-personal publisher.
    # All remain shallow; the private repository checkout uses checkout's
    # default shallow depth and does not broaden public branch authority.
    assert workflow.count("fetch-depth: 1") == 3
    assert "private_personal_publish:" in workflow
    assert "repository: iphoenk/fpl-reports-private" in workflow
    runtime_fetch = 'fetch --depth=1 origin "+refs/heads/${RUNTIME_BRANCH}:refs/remotes/origin/${RUNTIME_BRANCH}"'
    assert workflow.count(runtime_fetch) == 3
    assert workflow.count('AUTHORIZATION: basic $read_auth') >= 3
    assert 'V6_RUNTIME_READ_TOKEN: ${{ github.token }}' in workflow
    for token in ("runtime-data-v3", "runtime-data-v4", "runtime-data-v5"):
        assert token not in workflow


def test_v6_report_prefetch_auth_defaults_to_explicit_unavailable_not_invalid_configuration():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "FPL_AUTH_MODE: ${{ vars.FPL_AUTH_MODE || 'disabled' }}" in workflow
    assert "FPL_AUTH_MODE: ${{ vars.FPL_AUTH_MODE || 'session_cookie' }}" not in workflow
