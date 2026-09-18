"""A compact Inductive Miner with translucent DFG selection.

The recursion is the classical Inductive Miner (Leemans): base cases, then the
four cuts (exclusive choice, sequence, concurrency, loop), then fall-throughs
ending in a flower model.  What differs is *which* directly-follows graph the cut
detection runs on:

======  ==================================================================
variant graph used for cut detection
======  ==================================================================
IM      classical DFG only
IMto    translucent DFG only
IMts    classical DFG first, translucent DFG as fallback
IMtf    translucent DFG first, classical DFG as fallback
======  ==================================================================

With ``noise_threshold > 0`` the chosen graph is the frequency-weighted variant
with IMf-style filtering applied before cut detection.

Projections after a cut follow pm4py's Inductive Miner: exclusive choice routes
each trace to its best-matching group, loop splits each trace into do / redo
segments.  Two tau-loop fall-throughs recover loops the loop cut cannot see.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pm4py.objects.process_tree.obj import Operator, ProcessTree

from tpv.discovery.dfg import (
    Dfg,
    classical_dfg,
    filter_infrequent,
    frequent_translucent_dfg,
    translucent_dfg,
)
from tpv.log.types import TranslucentLog, TranslucentTrace, pi_act

VARIANTS = ("IM", "IMto", "IMts", "IMtf")

Groups = List[Set[str]]
CutResult = Tuple[Operator, Groups]


# --------------------------------------------------------------------------- #
# log helpers
# --------------------------------------------------------------------------- #
def _new_log(name: str) -> TranslucentLog:
    return TranslucentLog(name=name)


def _project_events(trace: TranslucentTrace, keep: Set[str]) -> TranslucentTrace:
    keep_f = frozenset(keep)
    return tuple(
        (act, frozenset(enabled) & keep_f) for (act, enabled) in trace if act in keep
    )


def _sublog_from(pairs, name: str) -> TranslucentLog:
    out = _new_log(name)
    for trace, count in pairs:
        out.variants[trace] += count
    return out


# --------------------------------------------------------------------------- #
# graph helpers
# --------------------------------------------------------------------------- #
def _adjacency(dfg: Dfg) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = {a: set() for a in dfg.activities}
    for (x, y) in dfg.edges:
        if x in adj and y in dfg.activities and x != y:
            adj[x].add(y)
    return adj


def _reachability(adj: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    reach: Dict[str, Set[str]] = {a: set(adj[a]) for a in adj}
    changed = True
    while changed:
        changed = False
        for a in adj:
            add: Set[str] = set()
            for b in reach[a]:
                add |= reach[b]
            if not add <= reach[a]:
                reach[a] |= add
                changed = True
    return reach


def _undirected_components(nodes: Set[str], adj: Dict[str, Set[str]]) -> Groups:
    und: Dict[str, Set[str]] = {a: set() for a in nodes}
    for a in nodes:
        for b in adj.get(a, ()):
            if b in nodes:
                und[a].add(b)
                und[b].add(a)
    seen: Set[str] = set()
    comps: Groups = []
    for a in nodes:
        if a in seen:
            continue
        stack, comp = [a], set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            seen.add(cur)
            stack.extend(und[cur] - comp)
        comps.append(comp)
    return comps


# --------------------------------------------------------------------------- #
# cuts
# --------------------------------------------------------------------------- #
def _xor_cut(dfg: Dfg) -> Optional[Groups]:
    nodes = set(dfg.activities)
    if len(nodes) < 2:
        return None
    comps = _undirected_components(nodes, _adjacency(dfg))
    return comps if len(comps) > 1 else None


def _sequence_cut(dfg: Dfg) -> Optional[Groups]:
    nodes = list(dfg.activities)
    if len(nodes) < 2:
        return None
    reach = _reachability(_adjacency(dfg))
    parent = {a: a for a in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in combinations(nodes, 2):
        # merge nodes that are mutually reachable or mutually unreachable
        if (b in reach[a]) == (a in reach[b]):
            parent[find(a)] = find(b)

    classes: Dict[str, Set[str]] = {}
    for a in nodes:
        classes.setdefault(find(a), set()).add(a)
    groups = list(classes.values())
    if len(groups) < 2:
        return None

    def before(gx: Set[str], gy: Set[str]) -> bool:
        return any(y in reach[x] for x in gx for y in gy)

    ordered: List[Set[str]] = []
    remaining = groups[:]
    while remaining:
        head = next(
            (
                g
                for g in remaining
                if not any(before(o, g) for o in remaining if o is not g)
            ),
            remaining[0],
        )
        ordered.append(head)
        remaining.remove(head)
    return ordered


def _concurrency_cut(dfg: Dfg) -> Optional[Groups]:
    nodes = set(dfg.activities)
    if len(nodes) < 2:
        return None
    adj = _adjacency(dfg)
    neg: Dict[str, Set[str]] = {a: set() for a in nodes}
    for a, b in combinations(sorted(nodes), 2):
        if b not in adj[a] or a not in adj[b]:
            neg[a].add(b)
            neg[b].add(a)
    comps = _undirected_components(nodes, neg)
    if len(comps) < 2:
        return None
    starts, ends = set(dfg.start), set(dfg.end)
    for comp in comps:
        if not comp & starts or not comp & ends:
            return None
    return comps


def _loop_cut(dfg: Dfg) -> Optional[Groups]:
    nodes = set(dfg.activities)
    if len(nodes) < 2:
        return None
    starts, ends = set(dfg.start), set(dfg.end)
    if not starts or not ends:
        return None
    adj = _adjacency(dfg)

    body = set(starts) | set(ends)
    rest = nodes - body
    other = _undirected_components(rest, adj) if rest else []

    redo_parts: Groups = []
    for comp in other:
        ok = True
        for a in comp:
            for b in adj[a]:
                if b in body and b not in starts:
                    ok = False
            for x in nodes:
                if a in adj.get(x, set()) and x in body and x not in ends:
                    ok = False
        if ok:
            redo_parts.append(comp)
        else:
            body |= comp
    if not redo_parts:
        return None
    return [body] + redo_parts


_CUTS = (
    (_xor_cut, Operator.XOR),
    (_sequence_cut, Operator.SEQUENCE),
    (_concurrency_cut, Operator.PARALLEL),
    (_loop_cut, Operator.LOOP),
)


def _find_cut_on(dfg: Dfg) -> Optional[CutResult]:
    for detector, operator in _CUTS:
        groups = detector(dfg)
        if groups is not None and len(groups) > 1 and all(groups):
            return operator, [set(g) for g in groups]
    return None


# --------------------------------------------------------------------------- #
# graph construction per variant
# --------------------------------------------------------------------------- #
def _classical_graph(log: TranslucentLog, nt: float) -> Dfg:
    dfg = classical_dfg(log)
    return filter_infrequent(dfg, nt) if nt > 0 else dfg


def _translucent_graph(log: TranslucentLog, nt: float) -> Dfg:
    if nt > 0:
        return filter_infrequent(frequent_translucent_dfg(log), nt)
    return translucent_dfg(log)


def _find_cut(log: TranslucentLog, variant: str, nt: float) -> Optional[CutResult]:
    classical = lambda: _classical_graph(log, nt)
    translucent = lambda: _translucent_graph(log, nt)
    order = {
        "IM": [classical],
        "IMto": [translucent],
        "IMts": [classical, translucent],
        "IMtf": [translucent, classical],
    }.get(variant)
    if order is None:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    for build in order:
        cut = _find_cut_on(build())
        if cut is not None:
            return cut
    return None


# --------------------------------------------------------------------------- #
# projections (operator specific)
# --------------------------------------------------------------------------- #
def _project_xor(log: TranslucentLog, groups: Groups) -> List[TranslucentLog]:
    logs = [_new_log(f"{log.name}|xor{i}") for i in range(len(groups))]
    for trace, count in log.variants.items():
        overlap = [sum(1 for e in trace if pi_act(e) in g) for g in groups]
        target = max(range(len(groups)), key=lambda i: (overlap[i], -i))
        logs[target].variants[_project_events(trace, groups[target])] += count
    return logs


def _project_generic(log: TranslucentLog, groups: Groups) -> List[TranslucentLog]:
    logs = []
    for i, g in enumerate(groups):
        sub = _new_log(f"{log.name}|g{i}")
        for trace, count in log.variants.items():
            sub.variants[_project_events(trace, g)] += count
        logs.append(sub)
    return logs


def _project_loop(log: TranslucentLog, groups: Groups) -> List[TranslucentLog]:
    do = groups[0]
    redo = set().union(*groups[1:])
    do_log = _new_log(f"{log.name}|do")
    redo_log = _new_log(f"{log.name}|redo")
    for trace, count in log.variants.items():
        do_seg: List = []
        redo_seg: List = []
        for e in trace:
            a = pi_act(e)
            if a in do:
                do_seg.append(e)
                if redo_seg:
                    redo_log.variants[_project_events(tuple(redo_seg), redo)] += count
                    redo_seg = []
            elif a in redo:
                redo_seg.append(e)
                if do_seg:
                    do_log.variants[_project_events(tuple(do_seg), do)] += count
                    do_seg = []
        if redo_seg:
            redo_log.variants[_project_events(tuple(redo_seg), redo)] += count
        do_log.variants[_project_events(tuple(do_seg), do)] += count
    return [do_log, redo_log]


# --------------------------------------------------------------------------- #
# base cases and fall-throughs
# --------------------------------------------------------------------------- #
def _leaf(label: Optional[str], parent: Optional[ProcessTree] = None) -> ProcessTree:
    return ProcessTree(label=label, parent=parent)


def _base_case(log: TranslucentLog) -> Optional[ProcessTree]:
    variants = log.variants
    if not variants or all(len(t) == 0 for t in variants):
        return _leaf(None)  # tau
    acts = log.activities
    if len(acts) == 1 and all(len(t) == 1 for t in variants):
        (only,) = tuple(acts)
        return _leaf(only)
    return None


def _empty_trace_split(log: TranslucentLog) -> Optional[TranslucentLog]:
    has_empty = any(len(t) == 0 for t in log.variants)
    has_nonempty = any(len(t) > 0 for t in log.variants)
    if has_empty and has_nonempty:
        return _sublog_from(
            ((t, c) for t, c in log.variants.items() if len(t) > 0),
            f"{log.name}|nonempty",
        )
    return None


def _activity_once_per_trace(log: TranslucentLog) -> Optional[str]:
    acts = sorted(log.activities)
    if len(acts) < 2:
        return None
    for a in acts:
        if all(sum(1 for e in t if pi_act(e) == a) == 1 for t in log.variants):
            return a
    return None


def _tau_loop_split(log: TranslucentLog, strict: bool) -> Optional[TranslucentLog]:
    """StrictTauLoop / TauLoop fall-through (pm4py).

    Split every trace at each position ``i`` where ``pi_act(e_i)`` is a start
    activity (and, when ``strict``, ``pi_act(e_{i-1})`` is an end activity).  If
    that yields more segments than traces, the log is a tau loop over the
    segments.
    """
    starts = set(classical_dfg(log).start)
    ends = set(classical_dfg(log).end)
    segments: List[Tuple[TranslucentTrace, int]] = []
    total_traces = 0
    for trace, count in log.variants.items():
        total_traces += count
        x = 0
        for i in range(1, len(trace)):
            if pi_act(trace[i]) in starts and (
                not strict or pi_act(trace[i - 1]) in ends
            ):
                segments.append((trace[x:i], count))
                x = i
        segments.append((trace[x:], count))
    if sum(c for _, c in segments) <= total_traces:
        return None
    return _sublog_from(segments, f"{log.name}|tauloop")


# --------------------------------------------------------------------------- #
# recursion
# --------------------------------------------------------------------------- #
def discover_tree(
    log: TranslucentLog,
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
    _depth: int = 0,
) -> ProcessTree:
    """Discover a process tree from a translucent log."""
    if _depth > 500:  # safety net against pathological recursion
        return _flower(log)

    split = _empty_trace_split(log)
    if split is not None:
        node = ProcessTree(operator=Operator.XOR)
        child = discover_tree(split, variant, noise_threshold, _depth + 1)
        child.parent = node
        node.children = [_leaf(None, node), child]
        return node

    base = _base_case(log)
    if base is not None:
        return base

    cut = _find_cut(log, variant, noise_threshold)
    if cut is not None:
        operator, groups = cut
        if operator == Operator.XOR:
            parts = _project_xor(log, groups)
        elif operator == Operator.LOOP:
            parts = _project_loop(log, groups)
        else:
            parts = _project_generic(log, groups)
        node = ProcessTree(operator=operator)
        children = [
            discover_tree(p, variant, noise_threshold, _depth + 1) for p in parts
        ]
        for c in children:
            c.parent = node
        node.children = children
        return node

    # fall-throughs
    a = _activity_once_per_trace(log)
    if a is not None:
        rest = _sublog_from(
            ((_project_events(t, log.activities - {a}), c) for t, c in log.variants.items()),
            f"{log.name}|no-{a}",
        )
        node = ProcessTree(operator=Operator.PARALLEL)
        right = discover_tree(rest, variant, noise_threshold, _depth + 1)
        right.parent = node
        node.children = [_leaf(a, node), right]
        return node

    for strict in (True, False):
        looped = _tau_loop_split(log, strict=strict)
        if looped is not None:
            node = ProcessTree(operator=Operator.LOOP)
            body = discover_tree(looped, variant, noise_threshold, _depth + 1)
            body.parent = node
            node.children = [body, _leaf(None, node)]
            return node

    return _flower(log)


def _flower(log: TranslucentLog) -> ProcessTree:
    """``*( tau, a_1, ..., a_n )`` -- redo any activity any number of times."""
    leaves = sorted(log.activities)
    if not leaves:
        return _leaf(None)
    node = ProcessTree(operator=Operator.LOOP)
    tau = _leaf(None, node)
    if len(leaves) == 1:
        node.children = [tau, _leaf(leaves[0], node)]
        return node
    redo = ProcessTree(operator=Operator.XOR, parent=node)
    redo.children = [_leaf(a, redo) for a in leaves]
    node.children = [tau, redo]
    return node


__all__ = ["discover_tree", "VARIANTS"]
