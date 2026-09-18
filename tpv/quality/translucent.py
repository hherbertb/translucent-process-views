"""Translucent conformance: fitness and precision that also score enabled sets.

Thin wrappers over the vendored implementation in :mod:`tpv.vendor.tconf`
(Beyel et al.).  Both build an alignment plus a reachability graph of the model,
so they are markedly slower than the pm4py measures -- they are opt-in
(``translucent=True`` on :func:`tpv.quality.metrics.model_quality`).

They need two extra packages (``rustworkx`` for the fitness reachability graph,
``automata-lib`` for the precision DFA).  When those are missing the functions
return ``nan`` instead of raising -- :func:`available` reports why.

* **translucent fitness** -- ``1 - sum(align_cost) / sum(bound_worst_case)`` where
  the alignment cost also penalises a mismatch between the enabled set recorded
  in the event and the activities enabled at the aligned model state.
* **translucent precision** -- mean over synchronous moves of
  ``|log_enabled ∩ model_enabled| / |model_enabled|``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import math
from typing import Dict, Optional

from pm4py.objects.petri_net.obj import Marking, PetriNet

from tpv.log.io import to_event_log
from tpv.log.types import TranslucentLog

_NAN = float("nan")
_REQUIRED = ("rustworkx", "automata")


def available() -> Optional[str]:
    """``None`` if translucent conformance can run, else a message naming the
    missing dependency."""
    missing = [m for m in _REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        pretty = {"automata": "automata-lib"}
        names = ", ".join(pretty.get(m, m) for m in missing)
        return f"translucent conformance needs: {names} (pip install {names})"
    return None


def _safe(fn) -> float:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            value = fn()
        if value is None:
            return _NAN
        value = float(value)
        return _NAN if math.isnan(value) else value
    except Exception:
        return _NAN


def translucent_fitness(
    log: TranslucentLog, net: PetriNet, im: Marking, fm: Marking
) -> float:
    if available() is not None:
        return _NAN
    event_log = to_event_log(log)

    def _run() -> float:
        from tpv.vendor.tconf import tfitness

        return tfitness.calculate_log_fitness(event_log, net, im, fm)

    return _safe(_run)


def translucent_precision(
    log: TranslucentLog, net: PetriNet, im: Marking, fm: Marking
) -> float:
    if available() is not None:
        return _NAN
    event_log = to_event_log(log)

    def _run() -> float:
        from tpv.vendor.tconf import precision

        return precision.translucent_precision_score(event_log, net, im, fm)

    return _safe(_run)


def translucent_conformance(
    log: TranslucentLog, net: PetriNet, im: Marking, fm: Marking
) -> Dict[str, float]:
    """Both measures at once."""
    return {
        "translucent_fitness": translucent_fitness(log, net, im, fm),
        "translucent_precision": translucent_precision(log, net, im, fm),
    }


__all__ = [
    "available",
    "translucent_fitness",
    "translucent_precision",
    "translucent_conformance",
]
