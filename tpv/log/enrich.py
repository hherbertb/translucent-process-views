"""Turn a classical event log into a translucent one using a process model.

This is the enrichment the translucent-process-mining literature already uses:
align a classical log against a model, keep the fitting traces, and read the
enabled activities off the replay state in the model [Beyel & van der Aalst,
*Creating Translucent Event Logs to Improve Process Discovery*, DQT@ICPM 2022;
reused in *Improving Process Discovery Using Translucent Activity
Relationships*, BPM 2024].  It is how the published Sepsis translucent logs
(Zenodo 10.5281/zenodo.14161549) were produced.

Why it matters here: the synthetic generators in :mod:`tpv.log.synth` write the
enabled sets by hand, so they encode exactly the relationships ``kappa`` reads.
Deriving the enabled sets from a marking instead produces behaviour the method
did not design, which is what an evaluation of the method actually needs.

:func:`split_and_enrich` implements the per-group variant that the hidden-context
setting calls for: partition a real log by a real case attribute, discover one
model per group, enrich each group with *its own* model, then drop the attribute.
The attribute becomes the ground truth that ``kappa`` has to recover from the
enabled activities alone -- exactly the situation the paper motivates, in which
the role is visible in the interface but redacted from the recording.

Note on fidelity to the source method: DQT@ICPM 2022 chooses, among the optimal
alignments, the one whose silent transitions fire latest, to collect as much
availability information as possible.  For a fitting trace an optimal alignment
has no log or model moves, so it is a replay path; we search those paths
directly, preferring at every step the fewest silent transitions before the
visible one (silent transitions fire as late as possible), and read the
tau-closed enabled set at each replay state.  A trace is kept only if some path
replays all of it and ends in the final marking.  Traces that do not fit are
dropped, and the retention rate is reported rather than hidden -- it can be
severe and is not uniform across groups.

Determinism: pm4py returns enabled transitions as a set, which iterates in
object-hash order and so differs between runs.  An earlier greedy replay took
the first silent path it met and never backtracked, so whether a trace was kept,
and which enabled sets it received, changed from run to run (road traffic,
group A: 59% to 97% retention on one and the same model).  Transitions are now
visited in a canonical order that depends only on the net's labels and place
names, and dead ends are backtracked.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from tpv.log.types import TranslucentLog, TranslucentTrace

__all__ = [
    "EnrichmentReport",
    "enabled_at_marking",
    "enrich_from_model",
    "split_and_enrich",
]


@dataclass
class EnrichmentReport:
    """What the enrichment did, per group -- never silently discard this.

    The fitting-trace filter can remove most of a log (in the BPM 2024 table the
    Sepsis log drops from 1050 cases to 20), and it removes exactly the traces
    the model explains least, so the retention rate belongs in any table built
    from an enriched log.
    """

    group: str = ""
    n_cases_in: int = 0
    n_cases_kept: int = 0
    n_activities: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def retention(self) -> float:
        return (self.n_cases_kept / self.n_cases_in) if self.n_cases_in else 0.0

    def __str__(self) -> str:
        return (f"{self.group or 'all'}: kept {self.n_cases_kept}/{self.n_cases_in} "
                f"cases ({self.retention:.1%}), {self.n_activities} activities"
                + (f"; {'; '.join(self.notes)}" if self.notes else ""))


def enabled_at_marking(net, marking) -> FrozenSet[str]:
    """Visible transition labels enabled at ``marking``, through silent steps.

    A transition is *enabled* here if it can fire after any sequence of silent
    (unlabelled) transitions, which is what makes the result comparable to what a
    user sees on a screen: taus are internal bookkeeping, not available actions.

    This is the closure computed inside
    ``tpv.vendor.tconf.trg_rx.TranslucentReachabilityGraph``; it is lifted out
    here so that enrichment does not have to build the whole reachability graph.
    Building it would impose a workflow-net requirement and a 2500-node cap that
    real per-group models routinely exceed, whereas walking one trace does not.
    """
    from pm4py.objects.petri_net.semantics import enabled_transitions, execute

    seen = {marking}
    queue = [marking]
    labels: set = set()
    while queue:
        m = queue.pop()
        for t in enabled_transitions(net, m):
            if t.label is None:                      # silent: look through it
                m_next = execute(t, net, m)
                if m_next is not None and m_next not in seen:
                    seen.add(m_next)
                    queue.append(m_next)
            else:
                labels.add(t.label)
    return frozenset(labels)


def _transition_key(t) -> tuple:
    """Order transitions by what they are, not by where they live in memory.

    Visible transitions from pm4py's miners carry random uuid names, so the key
    uses the label and the (counter-named, hence stable) input and output places.
    """
    return (t.label is not None, t.label or "",
            tuple(sorted(a.source.name for a in t.in_arcs)),
            tuple(sorted(a.target.name for a in t.out_arcs)),
            t.name if t.label is None else "")


def _canonical_enabled(net, marking) -> list:
    from pm4py.objects.petri_net.semantics import enabled_transitions

    return sorted(enabled_transitions(net, marking), key=_transition_key)


def _marking_key(marking) -> tuple:
    return tuple(sorted((p.name, n) for p, n in marking.items()))


def _visible_successors(net, marking, label: str) -> list:
    """Markings reached by firing ``label`` after zero or more silent transitions.

    Breadth-first over silent steps, so successors that need fewer silent
    transitions come first; ties follow the canonical transition order.
    """
    from pm4py.objects.petri_net.semantics import execute

    out, seen_after = [], set()
    frontier, seen = [marking], {_marking_key(marking)}
    while frontier:
        nxt = []
        for m in frontier:
            for t in _canonical_enabled(net, m):
                m_next = execute(t, net, m)
                if m_next is None:
                    continue
                if t.label == label:
                    k = _marking_key(m_next)
                    if k not in seen_after:
                        seen_after.add(k)
                        out.append(m_next)
                elif t.label is None and _marking_key(m_next) not in seen:
                    seen.add(_marking_key(m_next))
                    nxt.append(m_next)
        frontier = nxt
    return out


def _can_finish(net, marking, fm) -> bool:
    """``fm`` is reachable from ``marking`` through silent transitions alone."""
    from pm4py.objects.petri_net.semantics import execute

    goal = _marking_key(fm)
    seen, stack = {_marking_key(marking)}, [marking]
    while stack:
        m = stack.pop()
        if _marking_key(m) == goal:
            return True
        for t in _canonical_enabled(net, m):
            if t.label is None:
                m_next = execute(t, net, m)
                if m_next is not None and _marking_key(m_next) not in seen:
                    seen.add(_marking_key(m_next))
                    stack.append(m_next)
    return False


def _replay_to_translucent(net, im, activities: Sequence[str], fm=None) -> Optional[TranslucentTrace]:
    """Replay one activity sequence, recording the enabled set per event.

    Returns ``None`` if no replay path exists (or, with ``fm``, none that ends in
    the final marking).  The path is chosen deterministically: depth-first over
    the positions, trying successors with the fewest silent steps first, and
    backtracking out of dead ends, which are memoised per (position, marking).
    """
    n = len(activities)
    dead: set = set()

    def walk(i, marking):
        if i == n:
            return [] if fm is None or _can_finish(net, marking, fm) else None
        key = (i, _marking_key(marking))
        if key in dead:
            return None
        act = activities[i]
        enabled = enabled_at_marking(net, marking)
        if act in enabled:
            for m_next in _visible_successors(net, marking, act):
                rest = walk(i + 1, m_next)
                if rest is not None:
                    return [(act, enabled)] + rest
        dead.add(key)
        return None

    events = walk(0, im)
    return tuple(events) if events is not None else None


def enrich_from_model(
    variants: Dict[Tuple[str, ...], List[str]],
    net,
    im,
    fm=None,
    *,
    group: str = "",
    name: str = "enriched",
) -> Tuple[TranslucentLog, EnrichmentReport]:
    """Enrich classical variants with the enabled sets of a model's replay states.

    ``variants`` maps an executed-activity sequence to the case ids exhibiting
    it.  Traces the model cannot replay are dropped and counted.  Every event of
    the result satisfies ``pi_act(e) in pi_en(e)`` by construction, which is the
    consistency the hand-written generators do not get for free.
    """
    entries: List[Tuple[TranslucentTrace, str]] = []
    report = EnrichmentReport(group=group)
    acts: set = set()
    for seq, case_ids in variants.items():
        report.n_cases_in += len(case_ids)
        trace = _replay_to_translucent(net, im, seq, fm)
        if trace is None:
            continue
        report.n_cases_kept += len(case_ids)
        acts.update(a for a, _ in trace)
        for cid in case_ids:
            # TranslucentLog.from_traces distinguishes (trace, case_id) from a
            # bare trace by testing isinstance(item[1], str); a numeric case id
            # (as in the road-traffic log) would otherwise be read as part of
            # the trace itself
            entries.append((trace, str(cid)))
    report.n_activities = len(acts)
    if not entries:
        report.notes.append("no trace could be replayed on this model")
    return TranslucentLog.from_traces(entries, name=name), report


def split_and_enrich(
    variants_by_group: Dict[str, Dict[Tuple[str, ...], List[str]]],
    discover,
    *,
    name: str = "semi-real",
) -> Tuple[TranslucentLog, Dict[str, str], List[EnrichmentReport]]:
    """Per-group enrichment: one model per group, then forget the grouping.

    ``variants_by_group`` maps a group label (the value of the real case
    attribute that plays the role of hidden context) to that group's classical
    variants.  ``discover`` is called as ``discover(variants) -> (net, im, fm)``
    and should mine a model from one group's behaviour only.

    Returns the merged translucent log, the ground truth ``case id -> group``,
    and one :class:`EnrichmentReport` per group.  The returned log carries no
    trace of the grouping: recovering it is the task.

    Two things to check before trusting a result built this way.  First, that the
    per-group models actually differ -- if the attribute does not gate behaviour,
    there is nothing to recover and the experiment is vacuous.  Second, the
    retention rates in the reports: the fitting filter is a non-uniform
    selection, so a group that retains 10% of its cases is no longer that group.
    """
    entries: List[Tuple[TranslucentTrace, str]] = []
    ground_truth: Dict[str, str] = {}
    reports: List[EnrichmentReport] = []
    for group, variants in variants_by_group.items():
        net, im, fm = discover(variants)
        sub, report = enrich_from_model(variants, net, im, fm, group=group,
                                        name=f"{name}-{group}")
        reports.append(report)
        for trace, count in sub.variants.items():
            for cid in sub.case_ids[trace]:
                entries.append((trace, str(cid)))
                ground_truth[str(cid)] = group
    log = TranslucentLog.from_traces(entries, name=name)
    return log, ground_truth, reports


def variants_of(cases: Dict[str, Sequence[str]]) -> Dict[Tuple[str, ...], List[str]]:
    """``case id -> activity sequence``  ->  ``activity sequence -> case ids``."""
    out: Dict[Tuple[str, ...], List[str]] = {}
    for cid, seq in cases.items():
        out.setdefault(tuple(seq), []).append(cid)
    return out
