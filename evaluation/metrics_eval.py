"""Metrics for the evaluation experiments."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np
import pm4py

from evaluation.methods import Grouping, to_sublogs
from tpv.discovery.api import discover_petri_net, view_process_tree
from tpv.log.types import TranslucentLog, executed_projection, pi_en
from tpv.quality.agreement import adjusted_rand_index
from tpv.quality.metrics import model_quality
from tpv.views.views import induce_views

try:
    from sklearn.metrics import (
        adjusted_rand_score,
        homogeneity_completeness_v_measure,
        normalized_mutual_info_score,
    )

    _HAVE_SK = True
except Exception:  # pragma: no cover
    _HAVE_SK = False


# --------------------------------------------------------------------------- #
def n_groups(grouping: Grouping) -> int:
    return len(set(grouping.values()))


def _encode(labels):
    codes: Dict[object, int] = {}
    return [codes.setdefault(x, len(codes)) for x in labels]


def recovery(gt_case_labels: Dict[str, object], pred_case_labels: Dict[str, object]) -> Dict[str, float]:
    keys = list(gt_case_labels)
    a = [gt_case_labels[k] for k in keys]
    b = [pred_case_labels[k] for k in keys]
    out: Dict[str, float] = {"ari": adjusted_rand_index(a, b)}
    if _HAVE_SK:
        ai, bi = _encode(a), _encode(b)  # sklearn needs 1D integer label arrays
        out["ari_sk"] = float(adjusted_rand_score(ai, bi))
        out["nmi"] = float(normalized_mutual_info_score(ai, bi))
        h, c, v = homogeneity_completeness_v_measure(ai, bi)
        out["homogeneity"] = float(h)
        out["completeness"] = float(c)
        out["v_measure"] = float(v)
    # purity: each predicted group votes its majority true label
    by_pred: Dict[object, Counter] = defaultdict(Counter)
    for ta, tb in zip(a, b):
        by_pred[tb][ta] += 1
    correct = sum(cnt.most_common(1)[0][1] for cnt in by_pred.values())
    out["purity"] = correct / max(len(a), 1)
    return out


def attribute_informativeness(
    attrs: Optional[dict], gt_case_labels: Dict[str, object]
) -> Dict[str, float]:
    """NMI between each recorded case attribute and the hidden label.

    Clean attributes score high, noisy ones ~0.  Numerics are discretised into
    quintiles before the NMI is computed.
    """
    if not attrs or not _HAVE_SK:
        return {}
    keys = [k for k in gt_case_labels if k in attrs]
    if not keys:
        return {}
    labels = _encode([gt_case_labels[k] for k in keys])
    names = sorted({a for k in keys for a in attrs[k]})
    out: Dict[str, float] = {}
    for a in names:
        vals = [attrs[k].get(a) for k in keys]
        numeric = all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals
        )
        if numeric:
            arr = np.asarray(vals, dtype=float)
            edges = np.unique(np.quantile(arr, [0.2, 0.4, 0.6, 0.8]))
            code = np.digitize(arr, edges).tolist()
        else:
            code = _encode(vals)
        out[a] = float(normalized_mutual_info_score(labels, code))
    return out


# --------------------------------------------------------------------------- #
def _enabled_signature(trace) -> tuple:
    return tuple(tuple(sorted(pi_en(e))) for e in trace)


def enabled_incoherence(log: TranslucentLog, grouping: Grouping) -> Dict[str, float]:
    """How much a grouping mixes enabled-activity information.

    For every (group, classical variant) pair we count the number of distinct
    enabled-activity signatures.  A coherent grouping has ~1 signature per
    (group, variant); an over/under-separating grouping mixes several.
    """
    buckets: Dict[object, List] = defaultdict(list)
    for t, g in grouping.items():
        buckets[g].append(t)
    per_variant_counts: List[int] = []
    group_sig_entropy: List[float] = []
    for traces in buckets.values():
        by_variant: Dict[tuple, set] = defaultdict(set)
        sig_hist: Counter = Counter()
        for t in traces:
            by_variant[executed_projection(t)].add(_enabled_signature(t))
            sig_hist[_enabled_signature(t)] += log.variants.get(t, 1)
        per_variant_counts.extend(len(s) for s in by_variant.values())
        total = sum(sig_hist.values()) or 1
        ent = -sum((n / total) * math.log2(n / total) for n in sig_hist.values() if n)
        group_sig_entropy.append(ent)
    return {
        "mean_sig_per_variant": (sum(per_variant_counts) / len(per_variant_counts))
        if per_variant_counts else 1.0,
        "max_sig_per_variant": float(max(per_variant_counts) if per_variant_counts else 1),
        "mean_group_sig_entropy": (sum(group_sig_entropy) / len(group_sig_entropy))
        if group_sig_entropy else 0.0,
    }


# --------------------------------------------------------------------------- #
# No variant cap: the user asked for translucent fitness / precision by default
# with no size limit.  Kept as an identity hook so call sites need not change.
_VARIANT_CAP = 10 ** 9


def _capped(sublog: TranslucentLog) -> TranslucentLog:
    traces = sublog.trace_set()
    if len(traces) <= _VARIANT_CAP:
        return sublog
    top = sorted(traces, key=lambda t: -sublog.variants.get(t, 0))[:_VARIANT_CAP]
    return sublog.sublog(top)


def _hmean(a: float, b: float) -> float:
    """Harmonic mean (F1) of two scores; 0 if either is <= 0."""
    if a <= 0.0 or b <= 0.0:
        return 0.0
    return 2.0 * a * b / (a + b)


# A model discovered from a sub-log that mixes several hidden views (or a very
# noisy one) can be extremely loose -- many labelled / silent transitions, wide
# concurrency.  Alignment precision and, above all, the translucent reachability
# graph then allocate gigabytes and the Rust backend aborts the whole process
# (uncatchable from Python).  Past these sizes we fall back to the bounded-memory
# token-replay backend and skip the translucent measures for that sub-model.
_LOOSE_LABELLED_TR = 120
_LOOSE_TOTAL_TR = 260
_LOOSE_PLACES = 200


def _net_too_loose(net) -> bool:
    labelled = sum(1 for t in net.transitions if t.label)
    return (
        labelled > _LOOSE_LABELLED_TR
        or len(net.transitions) > _LOOSE_TOTAL_TR
        or len(net.places) > _LOOSE_PLACES
    )


def weighted_model_quality(
    sublogs: Sequence[TranslucentLog],
    mode: str = "mined",
    translucent: bool = False,
    identifier_views=None,
) -> Dict[str, float]:
    total = sum(l.n_cases for l in sublogs) or 1
    acc = {"fitness": 0.0, "precision": 0.0, "generalization": 0.0, "simplicity": 0.0}
    if translucent:
        acc.update({"translucent_fitness": 0.0, "translucent_precision": 0.0})
    for i, sub in enumerate(sublogs):
        if mode == "identifier" and identifier_views is not None:
            net, im, fm = pm4py.convert_to_petri_net(
                view_process_tree(identifier_views[i], mode="identifier")
            )
        else:
            net, im, fm = discover_petri_net(sub, variant="IMtf")
        loose = _net_too_loose(net)
        try:
            q = model_quality(
                _capped(sub), net, im, fm,
                backend="token" if loose else None,
                translucent=translucent and not loose,
            )
        except BaseException:  # pyo3 PanicException / MemoryError: drop this sub-model
            continue
        w = sub.n_cases / total
        acc["fitness"] += w * q.fitness
        acc["precision"] += w * q.precision
        acc["generalization"] += w * q.generalization
        acc["simplicity"] += w * q.simplicity
        if translucent:
            tf, tp = q.translucent_fitness, q.translucent_precision
            tf = 0.0 if tf is None or math.isnan(tf) else tf
            tp = 0.0 if tp is None or math.isnan(tp) else tp
            acc["translucent_fitness"] += w * tf
            acc["translucent_precision"] += w * tp
    # F1 = harmonic mean of the (case-weighted) fitness and precision
    acc["f1"] = _hmean(acc["fitness"], acc["precision"])
    if translucent:
        acc["translucent_f1"] = _hmean(acc["translucent_fitness"],
                                       acc["translucent_precision"])
    return acc


def models_to_coverage(sublogs: Sequence[TranslucentLog], target_fitness: float = 0.98) -> int:
    """Minimum #models (largest groups first) whose sub-logs each reach
    ``target_fitness`` and together cover > 90% of the cases."""
    total = sum(l.n_cases for l in sublogs) or 1
    ordered = sorted(sublogs, key=lambda l: -l.n_cases)
    covered = 0
    used = 0
    for sub in ordered:
        try:
            net, im, fm = discover_petri_net(sub, variant="IMtf")
            be = "token" if _net_too_loose(net) else None
            q = model_quality(_capped(sub), net, im, fm, backend=be)
            fit = q.fitness
        except BaseException:
            fit = 0.0
        if fit >= target_fitness:
            covered += sub.n_cases
            used += 1
        if covered / total > 0.90:
            break
    return used


__all__ = [
    "n_groups",
    "recovery",
    "attribute_informativeness",
    "enabled_incoherence",
    "weighted_model_quality",
    "models_to_coverage",
    "harmonic_f1",
]

# public alias for the F1 helper (used by the plotting / table code as a fallback
# when an older e2_quality.csv has no f1 / translucent_f1 columns)
harmonic_f1 = _hmean
