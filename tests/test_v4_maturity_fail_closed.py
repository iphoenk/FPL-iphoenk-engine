from __future__ import annotations

import pytest

from src.services.governance_service import _assert_no_critical_failure_erasure


def test_maturity_preserves_critical_failed_state() -> None:
    _assert_no_critical_failure_erasure({"DSS-09"}, {"critical_failed": ["DSS-09"]})


def test_maturity_fails_closed_if_critical_failure_is_erased() -> None:
    with pytest.raises(RuntimeError, match="cannot erase critical FAILED state"):
        _assert_no_critical_failure_erasure({"DSS-09"}, {"critical_failed": []})
