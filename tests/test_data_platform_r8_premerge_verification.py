from pathlib import Path


WORKFLOW = Path(".github/workflows/repository-governance.yml").read_text(encoding="utf-8")


def _v6_verify_job() -> str:
    start = WORKFLOW.index("  v6-verify:\n")
    end = WORKFLOW.index("  v6-publisher-config:\n", start)
    return WORKFLOW[start:end]


def test_r8_premerge_v6_verify_checks_out_exact_pull_request_head() -> None:
    job = _v6_verify_job()
    assert "ref: ${{ github.event.pull_request.head.sha }}" in job
    assert "EXPECTED_HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in job
    assert 'actual_head="$(git rev-parse HEAD)"' in job
    assert '[[ "$actual_head" == "$EXPECTED_HEAD_SHA" ]]' in job


def test_r8_premerge_v6_verify_runs_canonical_wave3_chaos_acceptance() -> None:
    job = _v6_verify_job()
    assert "tests/test_data_platform_wave3_chaos_matrix.py" in job
    assert "python -m src.runtime_v6.wave3_chaos_acceptance" in job
    assert "v6-wave3-chaos-acceptance-${{ github.run_id }}-${{ github.run_attempt }}" in job
    assert "Enforce Wave 3 chaos acceptance gate" in job
