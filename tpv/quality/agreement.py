"""Clustering-agreement metrics with no hard third-party dependency.

`adjusted_rand_index` is a self-contained implementation of the Hubert-Arabie
adjusted Rand index; it matches ``sklearn.metrics.adjusted_rand_score`` on the
cases used here but needs only the standard library.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Hashable, Sequence


def _comb2(n: int) -> int:
    return n * (n - 1) // 2


def adjusted_rand_index(labels_true: Sequence[Hashable], labels_pred: Sequence[Hashable]) -> float:
    """Adjusted Rand index between two labelings of the same items."""
    labels_true = list(labels_true)
    labels_pred = list(labels_pred)
    if len(labels_true) != len(labels_pred):
        raise ValueError("labelings must have the same length")
    n = len(labels_true)
    if n == 0:
        return 1.0

    contingency: "Counter[tuple]" = Counter(zip(labels_true, labels_pred))
    a = Counter(labels_true)
    b = Counter(labels_pred)

    sum_comb_c = sum(_comb2(v) for v in contingency.values())
    sum_comb_a = sum(_comb2(v) for v in a.values())
    sum_comb_b = sum(_comb2(v) for v in b.values())

    total = _comb2(n)
    if total == 0:
        return 1.0
    expected = sum_comb_a * sum_comb_b / total
    max_index = 0.5 * (sum_comb_a + sum_comb_b)
    if max_index == expected:
        return 1.0
    return (sum_comb_c - expected) / (max_index - expected)


def label_accuracy(labels_true: Sequence[Hashable], labels_pred: Sequence[Hashable]) -> float:
    """Best-match accuracy: map each predicted group to its majority true label."""
    labels_true = list(labels_true)
    labels_pred = list(labels_pred)
    if not labels_true:
        return 1.0
    by_pred: Dict[Hashable, "Counter"] = {}
    for t, p in zip(labels_true, labels_pred):
        by_pred.setdefault(p, Counter())[t] += 1
    mapping = {p: c.most_common(1)[0][0] for p, c in by_pred.items()}
    correct = sum(1 for t, p in zip(labels_true, labels_pred) if mapping[p] == t)
    return correct / len(labels_true)


__all__ = ["adjusted_rand_index", "label_accuracy"]
