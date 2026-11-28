from __future__ import annotations

import math


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> dict[str, float]:
    """
    Computes Wilson score confidence interval for a binomial proportion.
    Returns: {"value": float, "lower": float, "upper": float}
    """
    if total <= 0:
        return {"value": 0.0, "lower": 0.0, "upper": 1.0}

    # z-value for 95% confidence is 1.95996, for 90% is 1.64485, 99% is 2.57583
    if abs(confidence - 0.95) < 0.01:
        z = 1.95996
    elif abs(confidence - 0.90) < 0.01:
        z = 1.64485
    elif abs(confidence - 0.99) < 0.01:
        z = 2.57583
    else:
        z = 1.95996

    p = float(successes) / float(total)
    n = float(total)
    z2 = z * z

    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)

    return {
        "value": round(p, 4),
        "lower": round(lower, 4),
        "upper": round(upper, 4),
    }


def percentile(data: list[float], p: float) -> float:
    """Calculates p-th percentile (0 <= p <= 100) from list of numbers."""
    if not data:
        return 0.0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_d[int(k)])
    d0 = sorted_d[int(f)] * (c - k)
    d1 = sorted_d[int(c)] * (k - f)
    return round(float(d0 + d1), 2)
