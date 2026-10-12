import hashlib
import json
import os
import subprocess
import sys
import textwrap

import pytest

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/v12-integrated-report-runner.yml"


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


def _readback_script() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = 'FIRST_REMOTE_SHA="$FIRST_REMOTE_SHA" REPORT_PATH="$REPORT_PATH" PYTHONPATH=. python - <<\'PY\''
    start = text.index(marker)
    begin = text.index("          import hashlib\n", start)
    end = text.index("          PY\n", begin)
    return textwrap.dedent(text[begin:end])


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _fixture(tmp_path: Path, mode: str, *, ready_full: bool = True) -> tuple[Path, str]:
    repo = tmp_path / "private-reports"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "test")
    root = repo / "reports" / "2026-27" / "gw_6" / "occurrence"
    root.mkdir(parents=True)
    (repo / "latest").mkdir()
    inputs = {
        "report_bundle.json": b'{"status":"valid"}\n',
        "report_body.md": b"canonical MATCH or PRICE report\n",
        "serving_report.md": b"canonical DEEP serving report\n",
        "digest.json": b'{"status":"READY_FULL"}\n',
        "digest.md": b"# Digest\n",
        "execution_proof_private.json": b'{"run_id":"test"}\n',
    }
    for name, payload in inputs.items():
        (root / name).write_bytes(payload)
    (repo / "latest" / f"{mode.lower()}.json").write_bytes(inputs["digest.json"])
    digest = lambda name: hashlib.sha256(inputs[name]).hexdigest()
    receipt = {
        "report_mode": mode,
        "destination": "reports/2026-27/gw_6/occurrence",
        "delivery_status": "READY_FULL" if ready_full else "READY_DEGRADED",
        "canonical_bundle_sha256": digest("report_bundle.json"),
        "canonical_body_sha256": digest("serving_report.md" if mode == "DEEP" else "report_body.md"),
        "digest_sha256": digest("digest.json"),
        "digest_md_sha256": digest("digest.md"),
        "execution_proof_private_sha256": digest("execution_proof_private.json"),
        "native_content_format": "NOT_APPLICABLE",
        "native_content_chunk_count": 0,
        "native_content_remote_readback": "UNVERIFIED",
        "native_ui_acceptance": "UNVERIFIED",
    }
    (root / "delivery_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "source fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run_script(tmp_path: Path, mode: str, commit: str) -> subprocess.CompletedProcess[str]:
    cwd = tmp_path / "app"
    cwd.mkdir(exist_ok=True)
    env = {**os.environ, "FIRST_REMOTE_SHA": commit,
           "REPORT_MODE": mode, "REPORT_PATH": "reports/2026-27/gw_6/occurrence",
           "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-c", _readback_script()],
                          cwd=cwd, env=env, text=True, capture_output=True)


@pytest.mark.parametrize("mode", ["MATCH", "PRICE"])
def test_non_native_reports_remote_readback_pass_without_manifest(tmp_path: Path, mode: str):
    repo, sha = _fixture(tmp_path, mode)
    result = _run_script(tmp_path, mode, sha)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((repo / "reports/2026-27/gw_6/occurrence/delivery_receipt.json").read_text())
    assert receipt["private_remote_readback"] == "PASS"
    assert receipt["private_report_commit"] == sha
    assert receipt["native_content_remote_readback"] == "UNVERIFIED"
    assert receipt["native_ui_acceptance"] == "UNVERIFIED"


def test_deep_ready_full_fails_closed_without_native_manifest(tmp_path: Path):
    _, sha = _fixture(tmp_path, "DEEP")
    result = _run_script(tmp_path, "DEEP", sha)
    assert result.returncode != 0
    assert "DEEP READY_FULL missing native content transport" in result.stderr


def test_match_corrupted_canonical_bytes_fail_remote_readback(tmp_path: Path):
    repo, sha = _fixture(tmp_path, "MATCH")
    path = repo / "reports/2026-27/gw_6/occurrence/delivery_receipt.json"
    receipt = json.loads(path.read_text())
    receipt["canonical_bundle_sha256"] = "0" * 64
    path.write_text(json.dumps(receipt), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "tampered receipt")
    sha = _git(repo, "rev-parse", "HEAD")
    result = _run_script(tmp_path, "MATCH", sha)
    assert result.returncode != 0
    assert "remote occurrence hash mismatch: report_bundle.json" in result.stderr
