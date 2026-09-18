"""Grouping methods compared in the evaluation.

Every ``group_*`` takes a :class:`~tpv.log.types.TranslucentLog` and returns a
mapping ``{translucent_trace -> group_id}`` over ``log.trace_set()`` (or ``None``
if an optional dependency is missing, so the caller can skip it).

* ``group_global``                -- one model for the whole log (under-separates)
* ``group_kappa``                 -- our relationship-induced views (Def. 4.11)
* ``group_classical_variants``    -- one group per executed projection
* ``group_translucent_variants``  -- one group per exact translucent variant
* ``group_control_flow_clustering``-- trace clustering on executed-activity features [Song 2008]
* ``group_context_aware_clustering``-- + enabled-activity features [Bose 2009]
* ``group_trace2vec_clustering``  -- Doc2Vec embedding + k-means [De Koninck 2018]
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence

import numpy as np

from tpv.log.synth import CLEAN_ATTRS, NOISY_ATTRS, NUMERIC_ATTRS, ORACLE_ATTRS
from tpv.log.types import TranslucentLog, TranslucentTrace, executed_projection, pi_act, pi_en
from tpv.views.views import induce_views

Grouping = Dict[TranslucentTrace, object]

_HAVE_SKLEARN = True
try:
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score
except Exception:  # pragma: no cover
    _HAVE_SKLEARN = False


# --------------------------------------------------------------------------- #
# deterministic partitioning methods
# --------------------------------------------------------------------------- #
def group_global(log: TranslucentLog, **_) -> Grouping:
    return {t: 0 for t in log.trace_set()}


def group_kappa(log: TranslucentLog, **_) -> Grouping:
    views = induce_views(log)
    return {t: v.label for v in views for t in v.traces}


#: a view holding less than this share of the cases is treated as unsupported
KAPPA_SUPPORT = 0.01


def group_kappa_supported(log: TranslucentLog, theta: float = KAPPA_SUPPORT, **_) -> Grouping:
    """kappa, then fold the unsupported views into the supported ones.

    kappa never mixes hidden groups -- its homogeneity is 1.00 on every log we
    measured -- but noise in the enabled activities, and real control flow, make
    it split them: one corrupted event gives a trace an identifier of its own.
    Keeping only the views that hold at least ``theta`` of the cases and folding
    the remainder into the supported view whose availability profile they match
    best repairs exactly that failure, and keeps the number of views a result
    rather than an input.

    The profile is the number of times each activity was enabled, compared by
    cosine; ties are broken by view label, so the grouping stays deterministic.
    """
    views = induce_views(log)
    size = {v.label: sum(len(log.case_ids[t]) for t in v.traces) for v in views}
    total = sum(size.values()) or 1
    # Definition 4.13 breaks ties by the identifier of the view, so order by that and
    # not by the label: labels are "C1", "C2", ... in frequency order, so sorting them
    # lexicographically ("C1" < "C10" < "C2") is not a property of the views at all.
    ident = {v.label: v.identifier.canonical_str() for v in views}
    keep = sorted((l for l, s in size.items() if s >= theta * total),
                  key=lambda l: ident[l])
    if not keep:                                     # degenerate: keep the largest
        keep = [max(size, key=lambda l: (size[l], ident[l]))]

    def profile(traces) -> Counter:
        c: Counter = Counter()
        for t in traces:
            for _, en in t:
                c.update(en)
        return c

    prof = {v.label: profile(v.traces) for v in views if v.label in set(keep)}
    norm = {l: sum(x * x for x in c.values()) ** 0.5 or 1.0 for l, c in prof.items()}

    def nearest(t) -> str:
        p = profile([t])
        np_ = sum(x * x for x in p.values()) ** 0.5 or 1.0
        best, best_s = keep[0], -1.0
        for l in keep:                                # `keep` is sorted: stable ties
            q = prof[l]
            s = sum(p[k] * q[k] for k in p if k in q) / (np_ * norm[l])
            if s > best_s:
                best, best_s = l, s
        return best

    out: Grouping = {}
    kept = set(keep)
    for v in views:
        if v.label in kept:
            for t in v.traces:
                out[t] = v.label
        else:
            for t in v.traces:
                out[t] = nearest(t)
    return out


def group_kappa_acts(log: TranslucentLog, **_) -> Grouping:
    """Coarsest member of the kappa family: group by the availability alphabet.

    Def. 3.2 admits any abstraction function; kappa (Def. 4.10) keeps the order,
    the repetition and the block structure of the local choices, which on real
    control flow separates traces that belong to one hidden group.  This variant
    keeps only *which* activities were ever part of a local choice, so traces
    that offer the same options in a different order or a different number of
    times fall into one view.
    """
    out: Grouping = {}
    for t in log.trace_set():
        n = len(t)
        en = [pi_en(e) for e in t]
        nxt = [en[i + 1] if i < n - 1 else frozenset() for i in range(n)]
        acts: set = set()
        for i, e in enumerate(t):
            acts |= {pi_act(e)} | (en[i] - nxt[i])      # choice_sigma(i), Def. 4.3
        out[t] = frozenset(acts)
    return out


def kappa_identifiers(log: TranslucentLog) -> Dict[str, str]:
    return {v.label: v.identifier.canonical_str() for v in induce_views(log)}


def group_classical_variants(log: TranslucentLog, **_) -> Grouping:
    return {t: executed_projection(t) for t in log.trace_set()}


def group_translucent_variants(log: TranslucentLog, **_) -> Grouping:
    return {t: i for i, t in enumerate(log.trace_set())}


# --------------------------------------------------------------------------- #
# feature extraction for trace clustering
# --------------------------------------------------------------------------- #
def _control_flow_features(traces: Sequence[TranslucentTrace], activities: Sequence[str]) -> np.ndarray:
    acts = list(activities)
    idx = {a: i for i, a in enumerate(acts)}
    pair_idx: Dict[tuple, int] = {}
    rows: List[List[float]] = []
    # first pass: collect directly-follows pairs
    for t in traces:
        seq = executed_projection(t)
        for a, b in zip(seq, seq[1:]):
            pair_idx.setdefault((a, b), len(pair_idx))
    for t in traces:
        seq = executed_projection(t)
        counts = [0.0] * len(acts)
        for a in seq:
            if a in idx:
                counts[idx[a]] += 1.0
        pairs = [0.0] * len(pair_idx)
        for a, b in zip(seq, seq[1:]):
            pairs[pair_idx[(a, b)]] += 1.0
        n = max(len(seq), 1)
        rows.append([c / n for c in counts] + [p / n for p in pairs] + [float(len(seq))])
    X = np.asarray(rows, dtype=float)
    return _standardise(X)


def _enabled_features(traces: Sequence[TranslucentTrace], activities: Sequence[str]) -> np.ndarray:
    acts = list(activities)
    idx = {a: i for i, a in enumerate(acts)}
    sig_idx: Dict[frozenset, int] = {}
    for t in traces:
        for e in t:
            sig_idx.setdefault(pi_en(e) & frozenset(acts), len(sig_idx))
    rows: List[List[float]] = []
    for t in traces:
        bag = [0.0] * len(acts)
        sig = [0.0] * len(sig_idx)
        for e in t:
            en = pi_en(e) & frozenset(acts)
            for a in en:
                bag[idx[a]] += 1.0
            sig[sig_idx[en]] += 1.0
        n = max(len(t), 1)
        rows.append([b / n for b in bag] + [s / n for s in sig])
    return _standardise(np.asarray(rows, dtype=float))


def _standardise(X: np.ndarray) -> np.ndarray:
    if X.size == 0:
        return X
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #
def pick_k_silhouette(X: np.ndarray, kmax: int = 8) -> int:
    n = X.shape[0]
    if n < 3:
        return max(1, n)
    best_k, best_s = 2, -1.0
    for k in range(2, min(kmax, n - 1) + 1):
        try:
            labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
            if len(set(labels)) < 2:
                continue
            s = silhouette_score(X, labels)
        except Exception:
            continue
        if s > best_s:
            best_k, best_s = k, s
    return best_k


def _cluster(X: np.ndarray, k: int, algo: str) -> np.ndarray:
    n = X.shape[0]
    k = max(1, min(k, n))
    if k == 1 or n < 2:
        return np.zeros(n, dtype=int)
    if algo == "ward":
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)


def _clustering_grouping(
    log: TranslucentLog, X: np.ndarray, k: Optional[int], algo: str, tag: str
) -> Optional[Grouping]:
    if not _HAVE_SKLEARN:
        return None
    traces = log.trace_set()
    if k is None:
        k = pick_k_silhouette(X)
    labels = _cluster(X, int(k), algo)
    return {t: f"{tag}:{int(c)}" for t, c in zip(traces, labels)}


def group_control_flow_clustering(
    log: TranslucentLog, k: Optional[int] = None, algo: str = "kmeans", **_
) -> Optional[Grouping]:
    if not _HAVE_SKLEARN:
        return None
    X = _control_flow_features(log.trace_set(), sorted(log.activities))
    return _clustering_grouping(log, X, k, algo, f"cf-{algo}")


def group_context_aware_clustering(
    log: TranslucentLog, k: Optional[int] = None, algo: str = "kmeans", **_
) -> Optional[Grouping]:
    if not _HAVE_SKLEARN:
        return None
    acts = sorted(log.activities)
    traces = log.trace_set()
    X = np.hstack([_control_flow_features(traces, acts), _enabled_features(traces, acts)])
    X = _standardise(X)
    return _clustering_grouping(log, X, k, algo, f"ctx-{algo}")


def group_enabled_clustering(
    log: TranslucentLog, k: Optional[int] = None, algo: str = "kmeans", **_
) -> Optional[Grouping]:
    """Trace clustering on **enabled-activity features only** (no control flow).

    The "just use the enabled activities" baseline: bag-of-enabled plus
    enabled-set signatures, standardised, then KMeans / Ward.
    """
    if not _HAVE_SKLEARN:
        return None
    X = _enabled_features(log.trace_set(), sorted(log.activities))
    return _clustering_grouping(log, X, k, algo, f"en-{algo}")


# --------------------------------------------------------------------------- #
# attribute-based trace clustering -- clusters on *recorded* case attributes
# (the fair "if the context is in the log, slicing works" baseline)
# --------------------------------------------------------------------------- #
def _attr_names(feature_set: str) -> List[str]:
    if feature_set == "clean":
        return list(CLEAN_ATTRS)
    if feature_set == "noisy":
        return list(NOISY_ATTRS)
    if feature_set == "oracle":
        # `role` alone: the hidden label itself.  An upper bound, not a rival.
        return list(ORACLE_ATTRS)
    return list(CLEAN_ATTRS) + list(NOISY_ATTRS)


def _aggregate_attrs(cids: Sequence[str], attrs: dict, names: Sequence[str]) -> dict:
    """One attribute record per translucent trace: mean for numerics, majority
    vote for categoricals over the trace's cases."""
    rec: Dict[str, object] = {}
    for a in names:
        vals = [attrs[c][a] for c in cids if c in attrs and a in attrs[c]]
        if not vals:
            rec[a] = 0.0 if a in NUMERIC_ATTRS else "?"
        elif a in NUMERIC_ATTRS:
            rec[a] = float(sum(vals) / len(vals))
        else:
            rec[a] = Counter(vals).most_common(1)[0][0]
    return rec


def group_attribute_clustering(
    log: TranslucentLog,
    attrs: Optional[dict],
    feature_set: str = "clean",
    k: Optional[int] = None,
    algo: str = "kmeans",
) -> Optional[Grouping]:
    """Cluster traces on their cases' recorded attributes.

    ``feature_set`` is ``"clean"`` (informative but not identifying),
    ``"noisy"`` (uninformative), ``"all"`` (both), or ``"oracle"`` (the hidden
    label itself -- an upper bound, not a competing baseline).  Categoricals
    are one-hot encoded, numerics standardised.  Returns ``None`` if attributes
    or sklearn are unavailable.
    """
    if not _HAVE_SKLEARN or attrs is None:
        return None
    names = _attr_names(feature_set)
    traces = log.trace_set()
    recs = [_aggregate_attrs(log.case_ids[t], attrs, names) for t in traces]
    cat_levels: Dict[str, set] = {a: set() for a in names if a not in NUMERIC_ATTRS}
    for r in recs:
        for a in cat_levels:
            cat_levels[a].add(r[a])
    cols: List[np.ndarray] = []
    for a in names:
        if a in NUMERIC_ATTRS:
            cols.append(np.array([[float(r[a])] for r in recs], dtype=float))
        else:
            lv = sorted(cat_levels[a])
            pos = {v: i for i, v in enumerate(lv)}
            oh = np.zeros((len(recs), max(len(lv), 1)), dtype=float)
            for i, r in enumerate(recs):
                oh[i, pos[r[a]]] = 1.0
            cols.append(oh)
    X = _standardise(np.hstack(cols)) if cols else np.zeros((len(traces), 1))
    return _clustering_grouping(log, X, k, algo, f"attr-{feature_set}-{algo}")


def group_trace2vec_clustering(
    log: TranslucentLog, k: Optional[int] = None, **_
) -> Optional[Grouping]:
    try:
        from gensim.models.doc2vec import Doc2Vec, TaggedDocument
    except Exception:  # pragma: no cover
        return None
    if not _HAVE_SKLEARN:
        return None
    traces = log.trace_set()
    docs = []
    for i, t in enumerate(traces):
        tokens: List[str] = []
        for e in t:
            tokens.append(pi_act(e))
            tokens.append(pi_act(e) + "|" + ",".join(sorted(pi_en(e))))
        docs.append(TaggedDocument(tokens, [i]))
    dim = min(32, max(4, len(traces)))
    model = Doc2Vec(docs, vector_size=dim, min_count=1, epochs=60, workers=1, seed=0)
    X = _standardise(np.asarray([model.dv[i] for i in range(len(traces))], dtype=float))
    if k is None:
        k = pick_k_silhouette(X)
    labels = _cluster(X, int(k), "kmeans")
    return {t: f"t2v:{int(c)}" for t, c in zip(traces, labels)}


# --------------------------------------------------------------------------- #
# conversions
# --------------------------------------------------------------------------- #
def to_case_labels(log: TranslucentLog, grouping: Grouping) -> Dict[str, object]:
    return {cid: grouping[t] for t in log.trace_set() for cid in log.case_ids[t]}


def to_sublogs(log: TranslucentLog, grouping: Grouping) -> List[TranslucentLog]:
    buckets: Dict[object, List[TranslucentTrace]] = {}
    for t, g in grouping.items():
        buckets.setdefault(g, []).append(t)
    return [log.sublog(ts) for ts in buckets.values()]


# name -> callable ; those taking k use the ground-truth k (and, for clustering, also k=auto)
PARTITION_METHODS = {
    "global": group_global,
    "kappa": group_kappa,
    "kappa_supported": group_kappa_supported,
    "classical_variants": group_classical_variants,
    "translucent_variants": group_translucent_variants,
}

CLUSTERING_METHODS = {
    "cf_kmeans": lambda log, k: group_control_flow_clustering(log, k, "kmeans"),
    "cf_ward": lambda log, k: group_control_flow_clustering(log, k, "ward"),
    "ctx_kmeans": lambda log, k: group_context_aware_clustering(log, k, "kmeans"),
    "trace2vec": lambda log, k: group_trace2vec_clustering(log, k),
    "enabled": lambda log, k: group_enabled_clustering(log, k, "kmeans"),
}

# attribute-based clustering: name -> callable(log, attrs, k)
ATTR_METHODS = {
    "attr_clean": lambda log, attrs, k: group_attribute_clustering(log, attrs, "clean", k),
    "attr_noisy": lambda log, attrs, k: group_attribute_clustering(log, attrs, "noisy", k),
    "attr_all": lambda log, attrs, k: group_attribute_clustering(log, attrs, "all", k),
    "attr_oracle": lambda log, attrs, k: group_attribute_clustering(log, attrs, "oracle", k),
}


__all__ = [
    "Grouping",
    "group_global",
    "group_kappa",
    "kappa_identifiers",
    "group_classical_variants",
    "group_translucent_variants",
    "group_control_flow_clustering",
    "group_context_aware_clustering",
    "group_trace2vec_clustering",
    "group_enabled_clustering",
    "group_attribute_clustering",
    "pick_k_silhouette",
    "to_case_labels",
    "to_sublogs",
    "PARTITION_METHODS",
    "CLUSTERING_METHODS",
    "ATTR_METHODS",
]
