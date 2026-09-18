"""Translucent activity relationships.

Re-implementation of the relationships used by the translucent-activity-
relationships miner (Beyel & van der Aalst, Process Science 2025), computed over
the distinct translucent traces of a :class:`~tpv.log.types.TranslucentLog` with
variant multiplicities taken into account.

For consecutive events ``(e_i, e_{i+1})`` with executed activity ``x = pi_act(e_i)``:

* *directly-follows*: ``x -> a`` for every ``a`` still enabled in ``e_{i+1}``.
* *choice*: ``x`` and every ``a`` that was enabled in ``e_i`` but not in ``e_{i+1}``
  are in an exclusive-choice relation (symmetric).
* *parallel*: ``x`` and every ``a`` enabled in both ``e_i`` and ``e_{i+1}`` are in a
  parallel relation (symmetric).

Enabled activities are always restricted to the set of activities that are
actually executed somewhere in the log.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, FrozenSet, Set, Tuple

from tpv.log.types import TranslucentLog, pi_act, pi_en

Pair = Tuple[str, str]


def _universe(log: TranslucentLog) -> FrozenSet[str]:
    return log.activities


def _enabled_in_universe(event, universe: FrozenSet[str]) -> Set[str]:
    return set(pi_en(event)) & universe


def start_activities(log: TranslucentLog) -> Set[str]:
    """Translucent start activities: enabled at the first event of some trace."""
    universe = _universe(log)
    out: Set[str] = set()
    for trace in log.trace_set():
        if trace:
            out |= _enabled_in_universe(trace[0], universe)
    return out


def end_activities(log: TranslucentLog, strict: bool = False) -> Set[str]:
    """Translucent end activities: enabled at the last event of some trace.

    With ``strict`` also require the activity to actually occur last in at least
    one classical variant.
    """
    universe = _universe(log)
    out: Set[str] = set()
    for trace in log.trace_set():
        if trace:
            out |= _enabled_in_universe(trace[-1], universe)
    if strict:
        really_last = {pi_act(t[-1]) for t in log.trace_set() if t}
        out &= really_last
    return out


def start_activities_frequent(log: TranslucentLog) -> "Counter[str]":
    universe = _universe(log)
    out: "Counter[str]" = Counter()
    for trace, count in log.variants.items():
        if trace:
            for a in _enabled_in_universe(trace[0], universe):
                out[a] += count
    return out


def end_activities_frequent(log: TranslucentLog) -> "Counter[str]":
    universe = _universe(log)
    out: "Counter[str]" = Counter()
    for trace, count in log.variants.items():
        if trace:
            for a in _enabled_in_universe(trace[-1], universe):
                out[a] += count
    return out


def _consecutive(log: TranslucentLog):
    universe = _universe(log)
    for trace, count in log.variants.items():
        for idx in range(len(trace) - 1):
            cur, nxt = trace[idx], trace[idx + 1]
            yield (
                pi_act(cur),
                _enabled_in_universe(cur, universe),
                _enabled_in_universe(nxt, universe),
                count,
            )


def directly_follows(log: TranslucentLog) -> Dict[str, Set[str]]:
    rel: Dict[str, Set[str]] = {}
    for x, _cur_en, nxt_en, _c in _consecutive(log):
        rel.setdefault(x, set()).update(nxt_en)
    return rel


def directly_follows_frequent(log: TranslucentLog) -> "Counter[Pair]":
    out: "Counter[Pair]" = Counter()
    for x, _cur_en, nxt_en, count in _consecutive(log):
        for a in nxt_en:
            out[(x, a)] += count
    return out


def choice(log: TranslucentLog) -> Dict[str, Set[str]]:
    rel: Dict[str, Set[str]] = {}
    for x, cur_en, nxt_en, _c in _consecutive(log):
        for a in cur_en - nxt_en:
            rel.setdefault(x, set()).add(a)
            rel.setdefault(a, set()).add(x)
    return rel


def choice_frequent(log: TranslucentLog) -> "Counter[Pair]":
    out: "Counter[Pair]" = Counter()
    for x, cur_en, nxt_en, count in _consecutive(log):
        for a in cur_en - nxt_en:
            out[(x, a)] += count
            out[(a, x)] += count
    return out


def parallel(log: TranslucentLog) -> Dict[str, Set[str]]:
    rel: Dict[str, Set[str]] = {}
    for x, cur_en, nxt_en, _c in _consecutive(log):
        for a in cur_en & nxt_en:
            rel.setdefault(x, set()).add(a)
            rel.setdefault(a, set()).add(x)
    return rel


def parallel_frequent(log: TranslucentLog) -> "Counter[Pair]":
    out: "Counter[Pair]" = Counter()
    for x, cur_en, nxt_en, count in _consecutive(log):
        for a in cur_en & nxt_en:
            out[(x, a)] += count
            out[(a, x)] += count
    return out


__all__ = [
    "start_activities",
    "end_activities",
    "start_activities_frequent",
    "end_activities_frequent",
    "directly_follows",
    "directly_follows_frequent",
    "choice",
    "choice_frequent",
    "parallel",
    "parallel_frequent",
]
