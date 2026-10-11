"""Bounded owner-only bootstrap action contract; no real secrets/network."""
from pathlib import Path

WORKFLOW = Path(".github/workflows/v6-oidc-owner-bootstrap.yml")


def test_owner_only_issue_comment_enrollment_guard():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:\n    types: [created]" in text
    assert "github.actor == github.repository_owner" in text
    assert "github.event_name == 'issue_comment'" in text
    assert "github.event.issue.number == 431" in text
    assert "github.event.comment.body == '/fpl-oidc-enroll'" in text
    assert "environment: v12-private-reports-publisher" in text
    assert "concurrency:\n  group: fpl-private-oidc-enrollment" in text


def test_comment_cannot_request_reenrollment_or_expose_token():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.comment.body == '/fpl-oidc-reenroll'" not in text
    assert "FPL_OIDC_BOOTSTRAP_REFRESH_TOKEN: ${{ secrets.FPL_OIDC_BOOTSTRAP_REFRESH_TOKEN }}" in text
    assert "token: ${{ secrets.FPL_PRIVATE_REPORTS_TOKEN }}" in text
    assert "if [[ \" ${{ inputs.intent }} \" == \"REENROLL\" ]]" not in text
    assert "python -m src.runtime_v6.domains.acquisition.git_oidc_store" in text
    assert "echo $FPL_OIDC_BOOTSTRAP_REFRESH_TOKEN" not in text
