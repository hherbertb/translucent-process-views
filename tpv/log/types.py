"""Core data types for translucent event logs.

Follows Section 3.1 of the paper.

Definition 3.1 (Event, trace, translucent event log).  An event is a pair
``e = (E, a)`` where ``E`` is the set of enabled activities and ``a in E`` is the
executed activity.  We write ``pi_en(e) = E`` and ``pi_act(e) = a``.  A trace is a
finite sequence of events.  A translucent event log is a multiset of traces.

Here an event is stored as ``(a, frozenset(E))`` -- executed activity first so the
pair reads like ``pi_act`` / ``pi_en`` -- and a log is a ``collections.Counter``
mapping a translucent trace (tuple of events) to its multiplicity.
"""

from __future__ import annotations

import warnings
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Iterator, List, Tuple

#: ``(executed activity, frozenset of enabled activities)`` -- Definition 3.1.
TranslucentEvent = Tuple[str, FrozenSet[str]]

#: A finite sequence of translucent events -- Definition 3.1.
TranslucentTrace = Tuple[TranslucentEvent, ...]


def pi_act(event: TranslucentEvent) -> str:
    """Executed activity of an event -- ``pi_act`` in Definition 3.1."""
    return event[0]


def pi_en(event: TranslucentEvent) -> FrozenSet[str]:
    """Enabled activities of an event -- ``pi_en`` in Definition 3.1."""
    return event[1]


def executed_projection(trace: TranslucentTrace) -> Tuple[str, ...]:
    """Executed projection ``pi_act(sigma)`` of a trace -- Definition 3.2."""
    return tuple(pi_act(e) for e in trace)


@dataclass
class TranslucentLog:
    """A translucent event log: a multiset of translucent traces (Definition 3.1).

    ``variants`` maps each distinct translucent trace to the number of cases that
    exhibit it.  ``case_ids`` keeps the original case identifiers per trace so that
    exported sub-logs stay traceable.
    """

    variants: "Counter[TranslucentTrace]" = field(default_factory=Counter)
    case_ids: Dict[TranslucentTrace, List[str]] = field(default_factory=dict)
    name: str = "translucent-log"

    # -- construction ----------------------------------------------------------
    @classmethod
    def from_traces(
        cls,
        traces: Iterable[Tuple[TranslucentTrace, ...]],
        name: str = "translucent-log",
    ) -> "TranslucentLog":
        """Build a log from an iterable of ``(trace, case_id)`` or bare traces."""
        log = cls(name=name)
        for idx, item in enumerate(traces):
            if (
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[1], str)
            ):
                trace, case_id = item
            else:
                trace, case_id = item, str(idx)
            trace = _normalise_trace(trace)
            log.variants[trace] += 1
            log.case_ids.setdefault(trace, []).append(case_id)
        log.validate()
        return log

    # -- inspection ----------------------------------------------------------
    def __iter__(self) -> Iterator[TranslucentTrace]:
        return iter(self.variants)

    def __len__(self) -> int:
        """Number of cases (traces counted with multiplicity)."""
        return sum(self.variants.values())

    @property
    def n_cases(self) -> int:
        return sum(self.variants.values())

    @property
    def n_events(self) -> int:
        return sum(len(t) * c for t, c in self.variants.items())

    def trace_set(self) -> List[TranslucentTrace]:
        """Set ``Sigma_L`` of translucent traces occurring in ``L`` -- Definition 3.3."""
        return list(self.variants)

    @property
    def activities(self) -> FrozenSet[str]:
        """``pi_act(L)`` -- the set of activities executed in ``L`` (Definition 3.1)."""
        acts: set = set()
        for trace in self.variants:
            for event in trace:
                acts.add(pi_act(event))
        return frozenset(acts)

    def classical_variants(self) -> "Counter[Tuple[str, ...]]":
        """Classical variants ``V(L)`` -- Definition 3.2 (multiset of executed projections)."""
        out: "Counter[Tuple[str, ...]]" = Counter()
        for trace, count in self.variants.items():
            out[executed_projection(trace)] += count
        return out

    def sublog(
        self, traces: Iterable[TranslucentTrace], name: str | None = None
    ) -> "TranslucentLog":
        """View-induced sub-log ``L_C`` -- Definition 3.6 (multiplicities inherited)."""
        keep = set(traces)
        sub = TranslucentLog(name=name or f"{self.name}-sub")
        for trace, count in self.variants.items():
            if trace in keep:
                sub.variants[trace] = count
                sub.case_ids[trace] = list(self.case_ids.get(trace, []))
        return sub

    # -- validation ----------------------------------------------------------
    def validate(self) -> List[str]:
        """Warn (do not raise) about events whose executed activity is not enabled."""
        problems: List[str] = []
        for trace in self.variants:
            for pos, event in enumerate(trace, start=1):
                if pi_act(event) not in pi_en(event):
                    problems.append(
                        f"trace {executed_projection(trace)}: position {pos} "
                        f"executes {pi_act(event)!r} which is not in the enabled "
                        f"set {sorted(pi_en(event))}"
                    )
        if problems:
            warnings.warn(
                "translucent log has events whose executed activity is not "
                f"enabled ({len(problems)} occurrence(s)); the executed activity "
                "is still treated as enabled by the abstraction functions.",
                stacklevel=2,
            )
        return problems


def _normalise_trace(trace: Iterable) -> TranslucentTrace:
    """Coerce an arbitrary trace description into a ``TranslucentTrace``.

    Accepts events given as ``(act, enabled)`` with ``enabled`` any iterable of
    strings, or a plain activity string (enabled set becomes ``{act}``).
    """
    out: List[TranslucentEvent] = []
    for event in trace:
        if isinstance(event, str):
            out.append((event, frozenset({event})))
            continue
        act, enabled = event
        out.append((act, frozenset(enabled)))
    return tuple(out)
