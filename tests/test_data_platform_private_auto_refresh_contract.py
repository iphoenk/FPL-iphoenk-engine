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
    assert 'PRIVATE_PERSONAL_REFRESH=AUTH_UNAVAILABLE_SAVED_SNAPSHOT_FALLBACK' in private
    assert 'PUBLIC_CURRENT15_FALLBACK=OFFICIAL_SUBMITTED_PICKS' in private
    assert 'snapshot["bank"] = None' in private
    assert 'snapshot["free_transfers"] = None' in private
    assert 'snapshot["free_transfers_source"] = "NOT_SUPPORTED"' in private
    assert 'snapshot["hit_cost"] = None' in private
    assert 'row["purchase_price"] = None' in private
    assert 'row["selling_price"] = None' in private
    assert '"free_transfers": "NOT_SUPPORTED"' in private
    assert 'saved_generated >= slot' in private
    assert 'PRIVATE_PERSONAL_REFRESH=PASS' in private
    assert 'private personal 15/15 purchase and selling prices not verified' in private
    assert 'private free transfers not verified by authenticated official evidence' in private
    assert 'private personal bank is not verified' in private


def test_only_authenticated_ft_normalization_is_admissible():
    assert normalise_authenticated_free_transfers({"free_transfers": 3}) == (3, "OFFICIAL_EXPLICIT")
    assert normalise_authenticated_free_transfers({"limit": 5, "made": 2}) == (3, "AUTHENTICATED_LIMIT_MINUS_MADE")
    assert normalise_authenticated_free_transfers({"limit": None, "made": 0}) == (None, "UNLIMITED")
    assert normalise_authenticated_free_transfers({"bank": 100}) == (None, "NOT_SUPPORTED")
