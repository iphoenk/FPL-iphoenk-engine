from __future__ import annotations

import numpy as np
import pytest

from src.engines.v12_lineup_batch import LineupBatchError, python_round_vec


def test_python_round_vec_bitwise_matches_python_round_near_decimal_halves() -> None:
    rng = np.random.default_rng(668)
    for decimals in (6, 9):
        scale = float(10 ** decimals)
        # >=400k decimal-half centers, with both signs, plus six adjacent
        # float64 values on each side.  This yields >5.2M values per decimal
        # precision and locks the exact signed-zero / tie-to-even bit pattern.
        integers = rng.integers(0, 2_000_000, size=400_000, dtype=np.int64)
        centers = (integers.astype(np.float64) + 0.5) / scale
        centers[1::2] *= -1.0
        values = [centers]
        lo = centers.copy()
        hi = centers.copy()
        for _ in range(6):
            lo = np.nextafter(lo, -np.inf)
            hi = np.nextafter(hi, np.inf)
            values.extend((lo.copy(), hi.copy()))
        values.append(np.asarray([0.0, -0.0], dtype=np.float64))
        x = np.concatenate(values)
        assert x.size >= 5_000_000
        got = python_round_vec(x, decimals)
        expected = np.fromiter(
            (round(float(v), decimals) for v in x),
            dtype=np.float64,
            count=x.size,
        )
        assert np.array_equal(got.view(np.int64), expected.view(np.int64))


def test_python_round_vec_domain_guards() -> None:
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([np.nan]), 6)
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([1.0]), 12)
    with pytest.raises(LineupBatchError):
        python_round_vec(np.asarray([float(2**52)]), 0)
