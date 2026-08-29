from __future__ import annotations


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0] * len(values)
    for n, i in enumerate(order):
        out[i] = n + 1
    return out


def mae(actual, predicted):
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted lengths must match")
    return sum(abs(float(a) - float(p)) for a, p in zip(actual, predicted)) / max(1, len(actual))


def spearman(actual, predicted):
    if len(actual) < 2 or len(actual) != len(predicted):
        return None
    a = rank([float(x) for x in actual])
    p = rank([float(x) for x in predicted])
    n = len(a)
    d2 = sum((x - y) ** 2 for x, y in zip(a, p))
    return 1 - (6 * d2) / (n * (n * n - 1))


def calibration_error(actual, predicted, bins=5):
    if not actual:
        return None
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted lengths must match")
    pairs = sorted(zip([float(x) for x in predicted], [float(x) for x in actual]))
    groups = [pairs[i::bins] for i in range(bins)]
    errors = []
    for group in groups:
        if group:
            errors.append(abs(sum(x for x, _ in group) / len(group) - sum(y for _, y in group) / len(group)))
    return sum(errors) / len(errors) if errors else None
