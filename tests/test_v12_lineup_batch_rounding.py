from __future__ import annotations

import numpy as np
import pytest

from src.engines.v12_lineup_batch import LineupBatchError, python_round_vec


def test_python_round_vec_bitwise_matches_python_round_near_decimal_halves() -> None:
    rng = np.random.default_rng(668)
    for decimals in (6, 9):
        scale = float(10 ** decimals)
        # Exercise exact half points plus six adjacent float64 values on each side.
        integers = rng.integers(0, 2_000_000, size=20_000, dtype=np.int64)
        centers = (integers.astype(np.float64) + 0.5) / scale
        values = [centers]
        lo = centers.copy()
        hi = centers.copy()
        for _ in range(6):
            lo = np.nextafter(lo, -np.inf)
            hi = np.nextafter(hi, np.inf)
            values.extend((lo.copy(), hi.copy()))
        x = np.concatenate(values)
        got = python_round_vec(x, decimals)
        expected = np.asarray([round(float(v), decimals) for v in x], dtype=np.float64)
        assert np.array_equal(got.view(np.uint64), expected.view(np.uint64))


def test_python_round_vec_domain_guards() -> None:
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([np.nan]), 6)
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([1.0]), 12)
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([float(2**52)]), 0)
