"""Directly-follows graphs (classical and translucent) for the Inductive Miner."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Set, Tuple

from tpv.discovery import relations as rel
from tpv.log.types import TranslucentLog, executed_projection

Edge = Tuple[str, str]


@dataclass
class Dfg:
    """A directly-follows graph over a fixed activity set."""

    activities: FrozenSet[str] = frozenset()
    edges: "Counter[Edge]" = field(default_factory=Counter)
    start: "Counter[str]" = field(default_factory=Counter)
    end: "Counter[str]" = field(default_factory=Counter)

    def successors(self, a: str) -> Set[str]:
        return {y for (x, y) in self.edges if x == a}

    def predecessors(self, a: str) -> Set[str]:
        return {x for (x, y) in self.edges if y == a}

    def project(self, keep: Iterable[str]) -> "Dfg":
        keep = frozenset(keep)
        return Dfg(
            activities=keep,
            edges=Counter({e: c for e, c in self.edges.items() if e[0] in keep and e[1] in keep}),
            start=Counter({a: c for a, c in self.start.items() if a in keep}),
            end=Counter({a: c for a, c in self.end.items() if a in keep}),
        )


def classical_dfg(log: TranslucentLog) -> Dfg:
    """Standard directly-follows graph over executed projections (Definition 3.2)."""
    edges: "Counter[Edge]" = Counter()
    start: "Counter[str]" = Counter()
    end: "Counter[str]" = Counter()
    for trace, count in log.variants.items():
        seq = executed_projection(trace)
        if not seq:
            continue
        start[seq[0]] += count
        end[seq[-1]] += count
        for a, b in zip(seq, seq[1:]):
            edges[(a, b)] += count
    return Dfg(activities=log.activities, edges=edges, start=start, end=end)


def translucent_dfg(log: TranslucentLog, strict_end: bool = False) -> Dfg:
    """tDFG: edges are the union of directly-follows and parallel relations,
    with translucent start / end activities."""
    edges: "Counter[Edge]" = Counter()
    for source, targets in rel.directly_follows(log).items():
        for target in targets:
            edges[(source, target)] += 1
    for source, targets in rel.parallel(log).items():
        for target in targets:
            edges[(source, target)] += 1
    start = Counter({a: 1 for a in rel.start_activities(log)})
    end = Counter({a: 1 for a in rel.end_activities(log, strict=strict_end)})
    return Dfg(activities=log.activities, edges=edges, start=start, end=end)


def frequent_translucent_dfg(log: TranslucentLog, subtract_choice: bool = True) -> Dfg:
    """Frequency-weighted tDFG.

    Edge weight is the directly-follows / parallel frequency of the ordered pair
    minus the exclusive-choice frequency of the same pair; non-positive weights
    drop the edge (mirrors ``discover_frequent_dfg`` of the reference miner).
    """
    df_freq = rel.directly_follows_frequent(log)
    par_freq = rel.parallel_frequent(log)
    xor_freq = rel.choice_frequent(log) if subtract_choice else Counter()
    edges: "Counter[Edge]" = Counter()
    for pair in set(df_freq) | set(par_freq):
        weight = df_freq.get(pair, 0) + par_freq.get(pair, 0) - xor_freq.get(pair, 0)
        if weight > 0:
            edges[pair] = weight
    return Dfg(
        activities=log.activities,
        edges=edges,
        start=rel.start_activities_frequent(log),
        end=rel.end_activities_frequent(log),
    )


def filter_infrequent(dfg: Dfg, threshold: float) -> Dfg:
    """IMf-style noise filtering: for every node keep only outgoing edges whose
    weight is at least ``threshold`` times the node's strongest outgoing edge.
    Start / end markers are filtered the same way against their own maxima."""
    if threshold <= 0:
        return dfg
    kept: "Counter[Edge]" = Counter()
    for node in dfg.activities:
        out = {e: c for e, c in dfg.edges.items() if e[0] == node}
        if not out:
            continue
        cutoff = threshold * max(out.values())
        for e, c in out.items():
            if c >= cutoff:
                kept[e] = c
    # keep every node reachable: if a node lost all incoming edges but had some,
    # restore its single strongest incoming edge
    for node in dfg.activities:
        incoming = {e: c for e, c in dfg.edges.items() if e[1] == node}
        if incoming and not any(e[1] == node for e in kept):
            best = max(incoming, key=incoming.get)
            kept[best] = incoming[best]
    start = _filter_markers(dfg.start, threshold)
    end = _filter_markers(dfg.end, threshold)
    return Dfg(activities=dfg.activities, edges=kept, start=start, end=end)


def _filter_markers(markers: "Counter[str]", threshold: float) -> "Counter[str]":
    if not markers:
        return Counter()
    cutoff = threshold * max(markers.values())
    return Counter({a: c for a, c in markers.items() if c >= cutoff})


def project_log(log: TranslucentLog, keep: Iterable[str], name: str | None = None) -> TranslucentLog:
    """Project a translucent log onto ``keep``.

    Events whose executed activity is not in ``keep`` are dropped; the enabled
    set of every surviving event is intersected with ``keep`` so that the tDFG of
    the projected log stays well defined.
    """
    keep = frozenset(keep)
    out = TranslucentLog(name=name or f"{log.name}|proj")
    for trace, count in log.variants.items():
        new_trace = tuple(
            (act, frozenset(enabled) & keep)
            for (act, enabled) in trace
            if act in keep
        )
        out.variants[new_trace] += count
        out.case_ids.setdefault(new_trace, []).extend(log.case_ids.get(trace, []))
    return out


__all__ = [
    "Dfg",
    "classical_dfg",
    "translucent_dfg",
    "frequent_translucent_dfg",
    "filter_infrequent",
    "project_log",
]
