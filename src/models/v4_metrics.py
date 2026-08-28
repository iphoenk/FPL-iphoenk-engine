from __future__ import annotations

from typing import Iterable, Sequence


def mae_values(predicted: Sequence[float], actual: Sequence[float]) -> float | None:
    """Canonical mean absolute error for aligned numeric sequences."""
    values = [abs(float(a) - float(p)) for p, a in zip(predicted, actual)]
    return sum(values) / len(values) if values else None


def brier_values(probabilities: Sequence[float], outcomes: Sequence[float]) -> float | None:
    """Canonical Brier score for aligned probability/outcome sequences."""
    values = [(float(p) - float(o)) ** 2 for p, o in zip(probabilities, outcomes)]
    return sum(values) / len(values) if values else None


def rank_values(values: Sequence[float]) -> list[int]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0] * len(values)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    return ranks


def spearman_values(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    """Canonical Spearman rank correlation without tie correction, preserving V4 semantics."""
    if len(actual) != len(predicted) or len(actual) < 2:
        return None
    actual_ranks = rank_values([float(value) for value in actual])
    predicted_ranks = rank_values([float(value) for value in predicted])
    n = len(actual_ranks)
    distance = sum((a - p) ** 2 for a, p in zip(actual_ranks, predicted_ranks))
    return 1 - 6 * distance / (n * (n * n - 1))


def mae_rows(rows: Iterable[dict]) -> float | None:
    rows = list(rows)
    return mae_values(
        [float(row["predicted"]) for row in rows],
        [float(row["actual"]) for row in rows],
    )


def spearman_rows(rows: Iterable[dict]) -> float | None:
    rows = list(rows)
    return spearman_values(
        [float(row["actual"]) for row in rows],
        [float(row["predicted"]) for row in rows],
    )


def calibration_error_values(actual: Sequence[float], predicted: Sequence[float], bins: int = 5) -> float | None:
    if not actual or len(actual) != len(predicted):
        return None
    pairs = sorted(zip((float(value) for value in predicted), (float(value) for value in actual)))
    groups = [pairs[index::bins] for index in range(bins)]
    errors = []
    for group in groups:
        if group:
            mean_predicted = sum(pred for pred, _actual in group) / len(group)
            mean_actual = sum(actual_value for _pred, actual_value in group) / len(group)
            errors.append(abs(mean_predicted - mean_actual))
    return sum(errors) / len(errors) if errors else None


def calibration_error_rows(rows: Iterable[dict], bins: int = 5) -> float | None:
    rows = list(rows)
    return calibration_error_values(
        [float(row["actual"]) for row in rows],
        [float(row["predicted"]) for row in rows],
        bins=bins,
    )
