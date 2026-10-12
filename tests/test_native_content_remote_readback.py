from pathlib import Path


WORKFLOW = Path(".github/workflows/v12-integrated-report-runner.yml")


def test_remote_readback_checks_occurrence_latest_and_all_chunk_bytes():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'latest/native_content.manifest.json' in text
    assert 'latest native chunk mismatch' in text
    assert 'validate_manifest_chunks(manifest, files, canonical_body=body)' in text
    assert 'receipt["native_content_round_trip"] = "PASS"' in text
    assert 'receipt["native_content_truncation"] = "PASS"' in text
    assert 'receipt["native_content_commit"] = commit' in text


def test_remote_readback_does_not_promote_ui_verification():
    text = WORKFLOW.read_text(encoding="utf-8")
    readback_block = text[text.index('manifest["remote_readback"] = "PASS"'):text.index('if [ "$publisher_rc" -eq 0 ]', text.index('manifest["remote_readback"] = "PASS"'))]
    assert 'verification_status"] = "REMOTE_READBACK_PASS"' in readback_block
    assert 'native_ui_user_visible_acceptance' not in readback_block
    assert 'VERIFIED' not in readback_block
