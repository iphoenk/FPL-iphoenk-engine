"""Production V6 private rotating-auth rollout guardrails.

Only the isolated private publisher may auto-rotate; public ingestion is
independent. No test ever reads or creates real credentials.
"""
from pathlib import Path

from src.runtime_v6.domains.report_plane.personal_prefetch import (
    normalise_authenticated_free_transfers,
)


WORKFLOW = Path(".github/workflows/v6-natural-data-ingestion.yml")


def _jobs():
    text = WORKFLOW.read_text(encoding="utf-8")
    collect = text.split("  private_personal_publish:", 1)[0]
    private = text.split("  private_personal_publish:", 1)[1].split("  route-visible-report:", 1)[0]
    return collect, private


def test_rotating_oidc_only_in_protected_private_job():
    collect, private = _jobs()
    assert "environment: v12-private-reports-publisher" in private
    assert "FPL_OIDC_STORE_KEY: ${{ secrets.FPL_OIDC_STORE_KEY }}" in private
    assert "FPL_OIDC_CLIENT_ID: ${{ vars.FPL_OIDC_CLIENT_ID }}" in private
    assert "FPL_OIDC_STORE_DIR: private-reports" in private
    assert "FPL_OIDC_CONTRACT_VERIFIED: \"true\"" in private
    assert "vars.FPL_PRIVATE_AUTO_REFRESH_PAUSED == 'true'" in private
    assert "'disabled' || 'rotating_oidc'" in private
    assert "FPL_OIDC_STORE_KEY" not in collect
    assert "FPL_OIDC_CONTRACT_VERIFIED" not in collect
    assert "FPL_PRIVATE_AUTO_REFRESH_PAUSED" not in collect
    assert "FPL_OIDC_OWNER_CONTROLLED_GRANT" not in private
    assert "schedule:\n" not in private


def test_private_refresh_remains_public_nonblocking_and_finance_fail_closed():
    collect, private = _jobs()
    assert 'PRIVATE_PERSONAL_REFRESH=AUTH_UNAVAILABLE_NO_CURRENT_SNAPSHOT' in private
    assert 'SAVED_VALIDATED_SNAPSHOT' not in private
    assert 'shutil.copytree(saved_personal' not in private
    assert 'PUBLIC_CURRENT15_FALLBACK=OFFICIAL_SUBMITTED_PICKS' in private
    assert 'PRIVATE_PERSONAL_REFRESH=AUTH_UNAVAILABLE_NO_CURRENT_SNAPSHOT' in private
    assert 'saved_generated >= slot' not in private
    assert 'stale_snapshot_fallback' not in private
    assert 'PRIVATE_PERSONAL_REFRESH=PASS' in private
    assert 'private personal 15/15 purchase and selling prices not verified' in private
    assert 'private free transfers not verified by authenticated official evidence' in private
    assert 'private personal bank is not verified' in private
    # Remote may move between private refresh and publish, while an older
    # retry must never roll back authenticated personal state.
    assert 'git pull --rebase origin main' not in private
    assert 'git rebase --strategy-option=theirs origin/main' in private
    assert 'PRIVATE_PERSONAL_REMOTE_ORDER=STALE_LOCAL_BLOCKED' in private
    assert 'PRIVATE_PERSONAL_REMOTE_ORDER=NAIVE_TIMESTAMP' in private
    assert 'PRIVATE_PERSONAL_PUBLISH=REMOTE_MOVED_RETRY_' in private
    assert 'PRIVATE_PERSONAL_PUBLISH=RETRY_EXHAUSTED' in private
    assert 'for attempt in 1 2 3; do' in private


def test_private_refresh_reports_safe_prefetch_summary_and_distinguishes_missing_snapshot():
    _, private = _jobs()
    assert 'PRIVATE_PERSONAL_PREFETCH_REPORT_KIND=' in private
    assert 'PRIVATE_PERSONAL_PREFETCH_PERSONAL_REQUESTED=' in private
    assert 'PRIVATE_PERSONAL_PREFETCH_AUTH_STATE=' in private
    assert 'PRIVATE_PERSONAL_PREFETCH_PUBLIC_CORE=' in private
    assert 'PRIVATE_PERSONAL_REFRESH_FAILURE_CODE=SNAPSHOT_VALIDATION_FAILED' in private
    assert 'PRIVATE_PERSONAL_REFRESH=SNAPSHOT_VALIDATION_FAILED_NO_CURRENT_SNAPSHOT' in private
    assert 'PRIVATE_PERSONAL_REFRESH=AUTH_UNAVAILABLE_NO_CURRENT_SNAPSHOT' not in private.split(
        'if [[ ! -s "$refreshed_team" ]]; then', 1
    )[1].split('else', 1)[0]


def test_only_authenticated_ft_normalization_is_admissible():
    assert normalise_authenticated_free_transfers({"free_transfers": 3}) == (3, "OFFICIAL_EXPLICIT")
    assert normalise_authenticated_free_transfers({"limit": 5, "made": 2}) == (3, "AUTHENTICATED_LIMIT_MINUS_MADE")
    assert normalise_authenticated_free_transfers({"limit": None, "made": 0}) == (None, "UNLIMITED")
    assert normalise_authenticated_free_transfers({"bank": 100}) == (None, "NOT_SUPPORTED")
