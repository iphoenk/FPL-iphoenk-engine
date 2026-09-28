from __future__ import annotations

import sys

import pytest

from src.engines.v12_p6_runtime import P6RuntimeError, _run_command


def test_run_command_failure_reports_safe_stage_category_and_tail(tmp_path):
    log_path = tmp_path / "private.log"
    with pytest.raises(P6RuntimeError) as exc:
        _run_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stderr.write('V6_REPORT_PREFETCH_BINDING failed "
                    "target_report_slot_match=false token=DO_NOT_PRINT\\n'); "
                    "raise SystemExit(1)"
                ),
            ],
            cwd=tmp_path,
            env={},
            log_path=log_path,
            stage="integrated_report_runner",
        )
    message = str(exc.value)
    assert "stage=integrated_report_runner" in message
    assert "rc=1" in message
    assert "category=V6_REPORT_PREFETCH_BINDING" in message
    assert "target_report_slot_match=false" in message
    assert "DO_NOT_PRINT" not in message
    assert log_path.is_file()


def test_run_command_unknown_failure_is_fail_closed_without_private_payload(tmp_path):
    with pytest.raises(P6RuntimeError) as exc:
        _run_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stderr.write('manager_payload={private} random failure\\n'); "
                    "raise SystemExit(1)"
                ),
            ],
            cwd=tmp_path,
            env={},
            log_path=tmp_path / "private.log",
            stage="canonical_test",
        )
    message = str(exc.value)
    assert "category=CANONICAL_SUBPROCESS_FAILURE" in message
    assert "manager_payload" not in message
    assert "{private}" not in message
