"""The relationship-induced abstraction function ``kappa`` -- Section 4.

Every helper is one definition from the paper, named after it.  All functions are
pure and operate on a :data:`tpv.log.types.TranslucentTrace`; positions are
1-based to match the paper.
"""

from __future__ import annotations

from typing import FrozenSet, List, Set, Tuple

from tpv.log.types import TranslucentTrace, pi_act, pi_en
from tpv.views.identifier import Empty, Identifier, act, and_, seq, xor

Interval = Tuple[int, ...]  # a contiguous run of positions {p, ..., q}


def successor_enabled(sigma: TranslucentTrace, i: int) -> FrozenSet[str]:
    """``next_en(sigma, i)`` -- Definition 4.2.

    Enabled activities of the successor event, or the empty set for the last
    position (there is no successor, so final alternatives are treated as gone).
    """
    n = len(sigma)
    if i < n:
        return pi_en(sigma[i])  # sigma[i] is position i+1 (0-based)
    return frozenset()


def local_choice_set(sigma: TranslucentTrace, i: int) -> FrozenSet[str]:
    """``choice_sigma(i)`` -- Definition 4.3.

    The executed activity plus every activity that was enabled now but is gone at
    the next position.
    """
    e_i = sigma[i - 1]
    disappeared = pi_en(e_i) - successor_enabled(sigma, i)
    return frozenset({pi_act(e_i)}) | disappeared


def local_block(sigma: TranslucentTrace, i: int) -> Identifier:
    """``block_sigma(i)`` -- Definition 4.4 (local abstraction block).

    The executed activity if the local choice set is a singleton, otherwise an
    exclusive-choice block over it.
    """
    choice = local_choice_set(sigma, i)
    if len(choice) == 1:
        return act(next(iter(choice)))
    return xor(*(act(a) for a in choice))


def represented_activities(sigma: TranslucentTrace, i: int) -> FrozenSet[str]:
    """``acts_sigma(i)`` -- Definition 4.5 (equals the local choice set here)."""
    return local_choice_set(sigma, i)


def supports_parallel(sigma: TranslucentTrace, i: int, j: int) -> bool:
    """``i ~>par j`` -- Definition 4.6 (requires ``i < j``).

    Position ``i`` supports later position ``j`` as parallel iff the two tokens
    represent disjoint activity sets and every activity represented at ``j`` was
    enabled at ``i`` and remained enabled after the execution at ``i``.
    """
    if not i < j:
        raise ValueError("supports_parallel requires i < j")
    acts_i = represented_activities(sigma, i)
    acts_j = represented_activities(sigma, j)
    if acts_i & acts_j:
        return False
    still_enabled = pi_en(sigma[i - 1]) & successor_enabled(sigma, i)
    return acts_j <= still_enabled


def is_parallel_supported_interval(sigma: TranslucentTrace, interval: Interval) -> bool:
    """Parallel-supported interval -- Definition 4.7.

    An interval is parallel-supported iff every earlier position supports every
    later position as parallel.
    """
    positions = sorted(interval)
    for a in range(len(positions)):
        for b in range(a + 1, len(positions)):
            if not supports_parallel(sigma, positions[a], positions[b]):
                return False
    return True


def parallel_decomposition(sigma: TranslucentTrace) -> List[Interval]:
    """Left-to-right parallel decomposition ``I_sigma`` -- Definition 4.8.

    Scan left to right; at each position take the *largest* parallel-supported
    interval that starts there, else a singleton interval.
    """
    n = len(sigma)
    if n == 0:
        return []
    intervals: List[Interval] = []
    p = 1
    while p <= n:
        best_q = p
        for q in range(n, p, -1):  # try the largest interval first
            if is_parallel_supported_interval(sigma, tuple(range(p, q + 1))):
                best_q = q
                break
        intervals.append(tuple(range(p, best_q + 1)))
        p = best_q + 1
    return intervals


def interval_abstraction(sigma: TranslucentTrace, interval: Interval) -> Identifier:
    """``abs_sigma(I)`` -- Definition 4.9.

    A singleton interval keeps its local block; a longer interval becomes a
    parallel block over the local blocks of its positions.

    The ``and_`` can never collapse to a single member: Definition 4.6 requires
    ``acts(i) & acts(j) == set()`` for every pair in a parallel-supported
    interval, and a local choice set always contains its executed activity, so
    the blocks of two positions in one interval are always distinct.
    """
    positions = sorted(interval)
    if len(positions) == 1:
        return local_block(sigma, positions[0])
    return and_(*(local_block(sigma, k) for k in positions))


def parallel_decomposition_rightmost(sigma: TranslucentTrace) -> List[Interval]:
    """Right-to-left variant of Definition 4.8, for the tie-break ablation.

    Scans from the end and takes the largest parallel-supported interval that
    *ends* at the current position.  Not the method; used only to show whether
    the leftmost-longest choice in Definition 4.8 is load-bearing.
    """
    n = len(sigma)
    if n == 0:
        return []
    intervals: List[Interval] = []
    q = n
    while q >= 1:
        best_p = q
        for p in range(1, q):  # largest interval ending at q, so smallest p first
            if is_parallel_supported_interval(sigma, tuple(range(p, q + 1))):
                best_p = p
                break
        intervals.append(tuple(range(best_p, q + 1)))
        q = best_p - 1
    return list(reversed(intervals))


def parallel_decomposition_shortest(sigma: TranslucentTrace) -> List[Interval]:
    """Left-to-right, but taking the *shortest* non-trivial window (>= 2) that
    starts at the current position, else a singleton.  Ablation only."""
    n = len(sigma)
    if n == 0:
        return []
    intervals: List[Interval] = []
    p = 1
    while p <= n:
        best_q = p
        for q in range(p + 1, n + 1):  # smallest interval first
            if is_parallel_supported_interval(sigma, tuple(range(p, q + 1))):
                best_q = q
                break
        intervals.append(tuple(range(p, best_q + 1)))
        p = best_q + 1
    return intervals


DECOMPOSITIONS = {
    "leftmost_longest": parallel_decomposition,       # Definition 4.8 -- the method
    "rightmost_longest": parallel_decomposition_rightmost,
    "leftmost_shortest": parallel_decomposition_shortest,
}


def kappa(sigma: TranslucentTrace, decomposition: str = "leftmost_longest") -> Identifier:
    """Relationship-induced abstraction function ``kappa`` -- Definition 4.10.

    * empty trace -> ``epsilon``
    * one interval -> that interval's abstraction
    * several intervals -> a sequence of their abstractions

    ``decomposition`` selects the tie-break; the default is Definition 4.8.
    The alternatives exist only for the ablation that shows whether the choice
    changes the induced views.
    """
    if len(sigma) == 0:
        return Empty()
    try:
        decompose = DECOMPOSITIONS[decomposition]
    except KeyError:
        raise ValueError(
            f"unknown decomposition {decomposition!r}; "
            f"expected one of {sorted(DECOMPOSITIONS)}"
        ) from None
    intervals = decompose(sigma)
    if len(intervals) == 1:
        return interval_abstraction(sigma, intervals[0])
    return seq(*(interval_abstraction(sigma, I) for I in intervals))


__all__ = [
    "successor_enabled",
    "local_choice_set",
    "local_block",
    "represented_activities",
    "supports_parallel",
    "is_parallel_supported_interval",
    "parallel_decomposition",
    "parallel_decomposition_rightmost",
    "parallel_decomposition_shortest",
    "DECOMPOSITIONS",
    "interval_abstraction",
    "kappa",
]
