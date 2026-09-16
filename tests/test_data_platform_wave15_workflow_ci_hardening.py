from __future__ import annotations

import re
from pathlib import Path

from src.runtime_v6.domain_layout import MODULE_DOMAIN
from src.runtime_v6.domains.report_plane.delivery_integrity import resolve_report_slot_decision


WORKFLOW_DIR = Path(".github/workflows")
FLAT_RUNTIME_COMMAND = re.compile(r"python\s+-m\s+src\.runtime_v6\.([A-Za-z0-9_]+)")
CANONICAL_WORKFLOW_OWNERS = (
    "v6-natural-data-ingestion.yml",
    "v6-scheduler-watchdog.yml",
    "v6-core-recovery-guard.yml",
    "v6-ci.yml",
    "repository-governance.yml",
)


def test_operational_and_ci_workflows_do_not_invoke_migrated_flat_facades() -> None:
    offenders: list[str] = []
    for workflow_name in CANONICAL_WORKFLOW_OWNERS:
        path = WORKFLOW_DIR / workflow_name
        text = path.read_text(encoding="utf-8")
        for module_name in FLAT_RUNTIME_COMMAND.findall(text):
            if module_name in MODULE_DOMAIN:
                offenders.append(f"{path.name}:{module_name}")
    assert offenders == [], f"operational/CI workflows still invoke flat facades: {offenders}"


def test_canonical_v6_ci_contract_handles_cumulative_pr_surface() -> None:
    from src.platform.v6_ci_contract import is_v6_owned_path, requires_v6_verification

    assert is_v6_owned_path("src/runtime_v6/domains/report_plane/report_delivery.py") is True
    assert is_v6_owned_path("src/platform/production_path_governance_validate.py") is True
    assert is_v6_owned_path("README.md") is False
    assert requires_v6_verification(
        [
            "src/runtime_v6/domains/report_plane/report_delivery.py",
            "docs/unrelated-last-commit-note.md",
        ]
    ) is True
    assert requires_v6_verification(["README.md", "docs/general.md"]) is False


def test_repository_governance_uses_canonical_cumulative_diff_classifier() -> None:
    text = (WORKFLOW_DIR / "repository-governance.yml").read_text(encoding="utf-8")
    assert 'git diff --name-only "$BASE_SHA" "$HEAD_SHA"' in text
    assert "python src/platform/v6_ci_contract.py changed-paths" in text
    assert "grep -Eq '^(config/v6/" not in text


def test_v6_ci_path_filters_cover_ci_contract_and_control_workflows() -> None:
    text = (WORKFLOW_DIR / "v6-ci.yml").read_text(encoding="utf-8")
    for marker in (
        '"src/platform/v6_ci_contract.py"',
        '"src/platform/production_path_governance_validate.py"',
        '".github/workflows/v6-scheduler-watchdog.yml"',
        '".github/workflows/v6-core-recovery-guard.yml"',
        '".github/workflows/v6-wave3-proof.yml"',
    ):
        assert marker in text


def test_pr_and_post_merge_verification_ownership_are_explicit() -> None:
    governance = (WORKFLOW_DIR / "repository-governance.yml").read_text(encoding="utf-8")
    v6_ci = (WORKFLOW_DIR / "v6-ci.yml").read_text(encoding="utf-8")

    assert "github.event_name == 'pull_request'" in governance
    assert "v6-required-verify" in governance
    assert "v6-required-publisher-config" in governance
    assert "Post-merge full V6 verification belongs exclusively to v6-ci.yml." in governance

    assert 'if [[ "$EVENT_NAME" == "push" ]]' in v6_ci
    assert 'echo "v6_changed=true" >> "$GITHUB_OUTPUT"' in v6_ci
    assert "Execute Wave 3 canonical chaos matrix" in v6_ci
    assert "Enforce Wave 3 chaos acceptance gate" in v6_ci
    assert "v6-governance-gate" in v6_ci


def test_v6_success_cannot_close_due_visible_report_without_delivery_proof() -> None:
    decision = resolve_report_slot_decision(
        logical_slot="2026-09-16T12:30:00+07:00",
        report_type="DEEP",
        report_state="NOT_STARTED",
        v6_already_published=True,
        delivered_report_slot_id=None,
        delivery_proof_valid=False,
    )

    assert decision["v6_already_published"] is True
    assert decision["report_delivered"] is False
    assert decision["report_required"] is True
    assert decision["start_build"] is True
    assert decision["reason"] == "DUE_REPORT"
