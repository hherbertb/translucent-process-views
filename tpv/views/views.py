"""Relationship-induced process views -- Definitions 3.5, 3.6, 4.11."""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

from tpv.log.types import TranslucentLog, TranslucentTrace, executed_projection
from tpv.views.abstraction import kappa
from tpv.views.identifier import Identifier


@dataclass
class ProcessView:
    """A relationship-induced process view ``[sigma]_kappa`` -- Definition 3.5 / 4.11.

    Holds the shared abstraction identifier, the distinct translucent traces in
    the equivalence class, and the view-induced sub-log ``L_C`` (Definition 3.6).
    """

    identifier: Identifier
    traces: Tuple[TranslucentTrace, ...]
    sublog: TranslucentLog
    label: str = ""

    @property
    def key(self) -> str:
        return self.identifier.canonical_str()

    @property
    def frequency(self) -> int:
        """Number of cases assigned to this view."""
        return self.sublog.n_cases

    @property
    def n_variants(self) -> int:
        """Number of distinct classical variants in the view (Definition 3.6)."""
        return len(self.classical_variants())

    @property
    def n_translucent_traces(self) -> int:
        return len(self.traces)

    def classical_variants(self) -> "Counter[Tuple[str, ...]]":
        """``V(C)`` -- classical variants contained in the view (Definition 3.6)."""
        return self.sublog.classical_variants()

    def coverage(self, total_cases: int) -> float:
        return self.frequency / total_cases if total_cases else 0.0


def induce_views(log: TranslucentLog) -> List[ProcessView]:
    """Set of relationship-induced process views ``C_kappa(L)`` -- Definition 4.11.

    Partitions the trace set ``Sigma_L`` by equality of the abstraction identifier
    ``kappa``; returns views ordered by case frequency (descending), then by
    canonical identifier string.
    """
    groups: "OrderedDict[str, Tuple[Identifier, List[TranslucentTrace], int]]" = OrderedDict()
    for order, trace in enumerate(log.trace_set()):
        ident = kappa(trace)
        bucket = groups.get(ident.canonical_str())
        if bucket is None:
            groups[ident.canonical_str()] = (ident, [trace], order)
        else:
            bucket[1].append(trace)

    views: List[ProcessView] = []
    first_seen: Dict[str, int] = {}
    for ident, traces, order in groups.values():
        sub = log.sublog(traces, name=f"{log.name}::view")
        view = ProcessView(identifier=ident, traces=tuple(traces), sublog=sub)
        first_seen[view.key] = order
        views.append(view)

    # frequency descending; ties keep first-appearance order (matches the paper)
    views.sort(key=lambda v: (-v.frequency, first_seen[v.key]))
    for i, v in enumerate(views, start=1):
        v.label = f"C{i}"
        v.sublog.name = f"{log.name}::{v.label}"
    return views


def assign_view(log: TranslucentLog, views: List[ProcessView]) -> Dict[TranslucentTrace, str]:
    """Map every translucent trace of ``log`` to the label of its process view."""
    lookup: Dict[str, str] = {}
    for v in views:
        for t in v.traces:
            lookup[_trace_id(t)] = v.label
    return {t: lookup[_trace_id(t)] for t in log.trace_set()}


def view_variant_crosstab(log: TranslucentLog, views: List[ProcessView]) -> pd.DataFrame:
    """Classical-variant x view matrix of case counts.

    Illustrates the paper's observation (Section 4.6): one classical variant can
    appear in several views, and one view can contain several classical variants.
    Rows are classical variants, columns are view labels, cells are case counts.
    """
    labels = [v.label for v in views]
    rows: Dict[str, Dict[str, int]] = {}
    for v in views:
        for trace, count in v.sublog.variants.items():
            variant = " -> ".join(executed_projection(trace))
            rows.setdefault(variant, {lbl: 0 for lbl in labels})
            rows[variant][v.label] += count
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=labels)
    frame.index.name = "classical variant"
    return frame.sort_index()


def _trace_id(trace: TranslucentTrace) -> str:
    return repr(trace)
