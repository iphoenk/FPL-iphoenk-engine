from pathlib import Path


WORKFLOW = Path(".github/workflows/v6-wave3-proof.yml")


def test_wave3_natural_observer_only_accepts_successful_main_v6_ci_chaos_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Resolve latest successful Wave 3 chaos acceptance" in text
    assert 'name.startswith("v6-wave3-chaos-acceptance-")' in text
    assert 'run.get("name") == "FPL V6 CI contracts"' in text
    assert 'run.get("event") == "push"' in text
    assert 'run.get("head_branch") == "main"' in text
    assert 'run.get("status") == "completed"' in text
    assert 'run.get("conclusion") == "success"' in text
    assert 'run.get("head_sha") == os.environ["CHAOS_HEAD_SHA"]' in text


def test_wave3_window_receives_bound_chaos_provenance_without_runtime_write_permission():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '--chaos-acceptance "$RUNNER_TEMP/wave3-chaos-evidence/wave3-chaos-acceptance.json"' in text
    assert '--chaos-source-run-id "${{ steps.chaos.outputs.run_id }}"' in text
    assert '--chaos-source-head-sha "${{ steps.chaos.outputs.head_sha }}"' in text
    assert '--chaos-artifact-name "${{ steps.chaos.outputs.artifact_name }}"' in text
    assert "contents: write" not in text
    assert "git push" not in text
