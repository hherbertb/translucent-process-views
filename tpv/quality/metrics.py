"""Conformance metrics for view models, wrapping pm4py.

Alignment-based metrics are used while the log stays under a size cap; larger
logs fall back to token-based replay.  Every result records which backend ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pm4py
from pm4py.objects.petri_net.obj import Marking, PetriNet

from tpv.discovery.api import discover_petri_net, view_petri_net
from tpv.log.io import to_event_log
from tpv.log.types import TranslucentLog
from tpv.views.views import ProcessView

ALIGNMENT_CASE_CAP = 8000  # every evaluation log fits -> one uniform (time-bounded) backend

# Alignment-based fitness / precision are exact but can blow up on loose,
# highly-concurrent models (e.g. a model discovered from a sub-log that mixes
# several hidden views).  Bound the A* search per model and per trace; pm4py
# then returns a best-effort alignment instead of hanging.
ALIGN_MAX_TIME = 45.0
ALIGN_MAX_TIME_TRACE = 6.0

try:  # low-level evaluators so we can pass the time bounds
    from pm4py.algo.conformance.alignments.petri_net.algorithm import (
        Parameters as _AlnParams,
    )
    from pm4py.algo.evaluation.precision import algorithm as _precision_evaluator
    from pm4py.algo.evaluation.replay_fitness import algorithm as _fitness_evaluator

    _ALIGN_PARAMS = {
        _AlnParams.PARAM_MAX_ALIGN_TIME: ALIGN_MAX_TIME,
        _AlnParams.PARAM_MAX_ALIGN_TIME_TRACE: ALIGN_MAX_TIME_TRACE,
    }
    _HAVE_LOWLEVEL = True
except Exception:  # pragma: no cover - pm4py layout change
    _HAVE_LOWLEVEL = False
    _ALIGN_PARAMS = {}


def _aligned_fitness_precision(event_log, net, im, fm):
    """Time-bounded alignment fitness / precision (best effort)."""
    if _HAVE_LOWLEVEL:
        fr = _fitness_evaluator.apply(
            event_log, net, im, fm,
            variant=_fitness_evaluator.Variants.ALIGNMENT_BASED,
            parameters=dict(_ALIGN_PARAMS),
        )
        fitness = fr.get("log_fitness", fr.get("average_trace_fitness", 0.0))
        precision = _precision_evaluator.apply(
            event_log, net, im, fm,
            variant=_precision_evaluator.Variants.ALIGN_ETCONFORMANCE,
            parameters=dict(_ALIGN_PARAMS),
        )
        return float(fitness), float(precision)
    fit = pm4py.fitness_alignments(event_log, net, im, fm)
    fitness = fit.get("log_fitness", fit.get("average_trace_fitness", 0.0))
    precision = pm4py.precision_alignments(event_log, net, im, fm)
    return float(fitness), float(precision)


@dataclass
class Quality:
    fitness: float
    precision: float
    generalization: float
    simplicity: float
    backend: str
    n_cases: int
    translucent_fitness: Optional[float] = None
    translucent_precision: Optional[float] = None
    extra: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "fitness": self.fitness,
            "precision": self.precision,
            "generalization": self.generalization,
            "simplicity": self.simplicity,
            "backend": self.backend,
            "cases": self.n_cases,
        }
        if self.translucent_fitness is not None:
            out["translucent_fitness"] = self.translucent_fitness
        if self.translucent_precision is not None:
            out["translucent_precision"] = self.translucent_precision
        return out


def _backend_for(log: TranslucentLog, force: Optional[str] = None) -> str:
    if force in ("alignments", "token"):
        return force
    return "alignments" if log.n_cases <= ALIGNMENT_CASE_CAP else "token"


def model_quality(
    log: TranslucentLog,
    net: PetriNet,
    im: Marking,
    fm: Marking,
    backend: Optional[str] = None,
    translucent: bool = False,
) -> Quality:
    """Fitness / precision / generalization / simplicity of ``net`` on ``log``.

    With ``translucent=True`` also computes the enabled-set-aware translucent
    fitness and precision (slower; see :mod:`tpv.quality.translucent`).
    """
    event_log = to_event_log(log)
    chosen = _backend_for(log, backend)
    if chosen == "alignments":
        fitness, precision = _aligned_fitness_precision(event_log, net, im, fm)
    else:
        fit = pm4py.fitness_token_based_replay(event_log, net, im, fm)
        fitness = fit.get("log_fitness", 0.0)
        precision = pm4py.precision_token_based_replay(event_log, net, im, fm)
    generalization = pm4py.generalization_tbr(event_log, net, im, fm)
    simplicity = pm4py.simplicity_petri_net(net, im, fm)

    tfit = tprec = None
    if translucent:
        from tpv.quality.translucent import translucent_conformance

        tc = translucent_conformance(log, net, im, fm)
        tfit = tc["translucent_fitness"]
        tprec = tc["translucent_precision"]

    return Quality(
        fitness=float(fitness),
        precision=float(precision),
        generalization=float(generalization),
        simplicity=float(simplicity),
        backend=chosen,
        n_cases=log.n_cases,
        translucent_fitness=tfit,
        translucent_precision=tprec,
    )


def view_model_quality(
    view: ProcessView,
    mode: str = "identifier",
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
    backend: Optional[str] = None,
    translucent: bool = False,
) -> Quality:
    """Quality of a view's model measured on the view's own sub-log."""
    net, im, fm = view_petri_net(
        view, mode=mode, variant=variant, noise_threshold=noise_threshold
    )
    return model_quality(view.sublog, net, im, fm, backend=backend, translucent=translucent)


def global_vs_views(
    log: TranslucentLog,
    views: List[ProcessView],
    view_mode: str = "identifier",
    global_variant: str = "IMtf",
    noise_threshold: float = 0.0,
    backend: Optional[str] = None,
    translucent: bool = False,
) -> pd.DataFrame:
    """Compare one global model on the whole log with one model per process view.

    Two families of rows, one per process view each:

    * ``scope="global"``  -- the single global model (mined on the whole log)
      evaluated **on that view's sub-log**.
    * ``scope="per-view"`` -- the view's own model evaluated on its own sub-log.

    ``case_weight`` is the fraction of cases that fall in the view
    (``view.frequency / total cases``); the per-scope weights sum to 1.  The
    ``AGGREGATE`` row of each scope is the ``case_weight``-weighted mean of that
    scope's metric values -- i.e. the score an average *case* sees under that
    approach.  Comparing the two ``AGGREGATE`` rows is the head-to-head: "if every
    case were served by the global model" vs. "by its own view's model".
    """
    gnet, gim, gfm = discover_petri_net(
        log, variant=global_variant, noise_threshold=noise_threshold
    )
    rows: List[Dict[str, object]] = []
    total = log.n_cases or 1
    metric_cols = ["fitness", "precision", "generalization", "simplicity"]
    if translucent:
        metric_cols += ["translucent_fitness", "translucent_precision"]

    for view in views:
        w = view.frequency / total
        gq = model_quality(view.sublog, gnet, gim, gfm, backend=backend, translucent=translucent)
        rows.append({"scope": "global", "view": view.label, "case_weight": w, **gq.as_dict()})
        vq = view_model_quality(
            view, mode=view_mode, noise_threshold=noise_threshold,
            backend=backend, translucent=translucent,
        )
        rows.append({"scope": "per-view", "view": view.label, "case_weight": w, **vq.as_dict()})

    frame = pd.DataFrame(rows)
    for scope in ("global", "per-view"):
        part = frame[frame["scope"] == scope]
        wsum = part["case_weight"].sum() or 1.0
        agg = {"scope": scope, "view": "AGGREGATE", "case_weight": part["case_weight"].sum()}
        for col in metric_cols:
            if col not in part:
                continue
            agg[col] = float((part[col].fillna(0) * part["case_weight"]).sum() / wsum)
        agg["backend"] = ",".join(sorted(set(part["backend"])))
        agg["cases"] = int(part["cases"].sum())
        frame = pd.concat([frame, pd.DataFrame([agg])], ignore_index=True)
    return frame


__all__ = [
    "Quality",
    "ALIGNMENT_CASE_CAP",
    "model_quality",
    "view_model_quality",
    "global_vs_views",
]
