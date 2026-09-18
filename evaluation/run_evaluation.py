"""Evaluation harness for "Discovering Hidden Process Views from Translucent
Event Logs" (ICPM 2026).

Tests the four claims of the introduction against related-work baselines over
big, varied synthetic logs with a known hidden context:

  C1  a single global model under-separates
  C2  classical-variant grouping over-separates and mixes enabled-activity info
  C3  exact translucent-variant grouping over-separates even more
  C4  kappa recovers the hidden context with no distance function / cluster count
  C5  per-view models beat global / clustering / variant discovery, at fewer models

Experiments:
  E1  separation & recovery   -> results/e1_separation.csv
  E2  model quality           -> results/e2_quality.csv
  E3  robustness sweeps       -> results/e3_sweeps.csv
  E4  task-mining case study  -> results/e4_taskmining.csv
plus results/summary.csv, results/*.tex and evaluation/figures/fig_*.{pdf,png}.

Usage::

    python evaluation/run_evaluation.py --quick        # ~1 min, used by tests
    python evaluation/run_evaluation.py --full         # default, a few minutes
    python evaluation/run_evaluation.py --full --translucent
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from evaluation import methods as M
from evaluation import plots
from evaluation.metrics_eval import (
    attribute_informativeness,
    enabled_incoherence,
    harmonic_f1,
    models_to_coverage,
    n_groups,
    recovery,
    weighted_model_quality,
)
from tpv.log.synth import (
    ATTRIBUTE_SCHEMA,
    LOG_SPECS,
    build_all,
    k_view_log,
    running_example_log,
)
from tpv.views.views import induce_views

ROOT = Path(__file__).resolve().parent
DEF_OUT = ROOT / "results"
DEF_FIG = ROOT / "figures"

_CLUSTERING = ["cf_kmeans", "cf_ward", "ctx_kmeans", "trace2vec", "enabled"]

# Every clustering baseline degrades to ``None`` when its dependency is missing
# (methods.py), and a ``None`` grouping is silently skipped in E1/E5.  That is
# how a table can come out missing a whole approach row with no warning -- and
# it is how the published tables and evaluation/results/ came to disagree.  A
# paper run must therefore fail loudly rather than quietly drop a baseline.
_REQUIRED_FOR_PAPER = {
    "gensim": "D2V-TC (trace2vec) representation-learning clustering",
    "sklearn": "every clustering baseline (CF-TC, CTX-TC, EN-TC, D2V-TC, ATTR-TC)",
}


def check_environment(quick: bool) -> None:
    """Refuse a paper-grade run when a baseline's dependency is missing.

    ``--quick`` is the smoke test used by the test suite and may run degraded;
    a full run produces the paper's tables and must not silently omit a row.
    """
    import importlib.util

    missing = [
        (mod, what)
        for mod, what in _REQUIRED_FOR_PAPER.items()
        if importlib.util.find_spec(mod) is None
    ]
    if not missing:
        return
    body = "\n".join(
        f"  - {mod!r} is not installed -> would silently drop {what}"
        for mod, what in missing
    ) + f"\n\nInterpreter: {sys.executable}\n"
    fix = (
        "Install the pinned environment and re-run:\n"
        "  python -m venv venv\n"
        "  venv/Scripts/python -m pip install -r requirements.txt\n"
        "  venv/Scripts/python evaluation/run_evaluation.py --full"
    )
    if quick:
        print(
            "WARNING: --quick smoke run continuing with baselines missing; its "
            "output is NOT paper-grade.\n" + body + fix,
            file=sys.stderr,
        )
        return
    raise SystemExit(
        "refusing to run: the resulting tables would be missing baselines.\n"
        + body + fix + "\nPass --quick to allow a degraded smoke run."
    )


def _cluster_call(name, log, k):
    if name == "cf_kmeans":
        return M.group_control_flow_clustering(log, k, "kmeans")
    if name == "cf_ward":
        return M.group_control_flow_clustering(log, k, "ward")
    if name == "ctx_kmeans":
        return M.group_context_aware_clustering(log, k, "kmeans")
    if name == "trace2vec":
        return M.group_trace2vec_clustering(log, k)
    if name == "enabled":
        return M.group_enabled_clustering(log, k, "kmeans")
    raise ValueError(name)


# --------------------------------------------------------------------------- #
# E1 -- separation & recovery
# --------------------------------------------------------------------------- #
def experiment_separation(quick: bool, seeds: list[int]) -> pd.DataFrame:
    rows = []
    for seed in seeds:
        for name, log, gt, attrs in build_all(quick, seed=seed):
            gt_cases = dict(gt) if gt else None
            k = len(set(gt.values())) if gt else None
            groupings = {
                "global": M.group_global(log),
                "kappa": M.group_kappa(log),
                "kappa_supported": M.group_kappa_supported(log),
                "classical_variants": M.group_classical_variants(log),
                "translucent_variants": M.group_translucent_variants(log),
            }
            for cname in _CLUSTERING:
                if k is not None:
                    g = _cluster_call(cname, log, k)
                    if g is not None:
                        groupings[f"{cname}@k"] = g
                g = _cluster_call(cname, log, None)
                if g is not None:
                    groupings[f"{cname}@auto"] = g
            for aname, afn in M.ATTR_METHODS.items():
                if attrs is None:
                    continue
                if k is not None:
                    g = afn(log, attrs, k)
                    if g is not None:
                        groupings[f"{aname}@k"] = g
                g = afn(log, attrs, None)
                if g is not None:
                    groupings[f"{aname}@auto"] = g

            for method, grouping in groupings.items():
                r = (recovery(gt_cases, M.to_case_labels(log, grouping))
                     if gt_cases else {})
                inc = enabled_incoherence(log, grouping)
                rows.append({
                    "log": name, "seed": seed, "method": method,
                    "k": k, "n_groups": n_groups(grouping),
                    "ratio_to_k": (n_groups(grouping) / k) if k else float("nan"),
                    "ari": r.get("ari", float("nan")),
                    "nmi": r.get("nmi", float("nan")),
                    "v_measure": r.get("v_measure", float("nan")),
                    # homogeneity says whether a grouping ever mixes hidden labels,
                    # completeness whether it splits one across views: kappa's failure
                    # mode is the second, and Sect. 5.4 quotes the first
                    "homogeneity": r.get("homogeneity", float("nan")),
                    "completeness": r.get("completeness", float("nan")),
                    "purity": r.get("purity", float("nan")),
                    "sig_per_variant": inc["mean_sig_per_variant"],
                    "group_sig_entropy": inc["mean_group_sig_entropy"],
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# E2 -- model quality
# --------------------------------------------------------------------------- #
def experiment_quality(quick: bool, translucent: bool) -> pd.DataFrame:
    rows = []
    for name, log, gt, attrs in build_all(quick, seed=0):
        k = len(set(gt.values())) if gt else len(induce_views(log))
        views = induce_views(log)

        specs = [
            ("global", [log], "mined", None),
            ("kappa", [v.sublog for v in views], "mined", None),
            ("kappa_supported",
             M.to_sublogs(log, M.group_kappa_supported(log)), "mined", None),
            ("kappa_identifier", [v.sublog for v in views], "identifier", views),
            ("classical_variants",
             M.to_sublogs(log, M.group_classical_variants(log)), "mined", None),
            ("translucent_variants",
             M.to_sublogs(log, M.group_translucent_variants(log)), "mined", None),
        ]
        # every grouping the partition experiment scores: each clustering /
        # attribute family at k = ground truth AND k = silhouette
        for cname in _CLUSTERING:
            for suffix, kk in (("@k", k), ("@auto", None)):
                g = _cluster_call(cname, log, kk)
                if g is not None:
                    specs.append((f"{cname}{suffix}",
                                  M.to_sublogs(log, g), "mined", None))
        for aname, afn in M.ATTR_METHODS.items():
            if attrs is None:
                continue
            for suffix, kk in (("@k", k), ("@auto", None)):
                g = afn(log, attrs, kk)
                if g is not None:
                    specs.append((f"{aname}{suffix}",
                                  M.to_sublogs(log, g), "mined", None))

        for method, sublogs, mode, idviews in specs:
            q = weighted_model_quality(sublogs, mode=mode, translucent=translucent,
                                       identifier_views=idviews)
            row = {"log": name, "method": method, "n_cases": log.n_cases,
                   "n_models": len(sublogs),
                   "models_to_cov": models_to_coverage(sublogs), **q}
            rows.append(row)
    frame = pd.DataFrame(rows)
    num = ["fitness", "precision", "f1", "generalization", "simplicity",
           "translucent_fitness", "translucent_precision", "translucent_f1"]
    for c in num:
        if c in frame:
            frame[c] = frame[c].round(3)
    return frame


# --------------------------------------------------------------------------- #
# E3 -- robustness sweeps
# --------------------------------------------------------------------------- #
def _clustering_ari_stats(log, gt_cases, k):
    """(mean, best) recovery ARI over the fixed control-flow / enabled clustering
    set, each given the ground-truth k.  `best` is an oracle upper bound (it picks
    the run using the metric being reported); `mean` is the honest baseline."""
    vals = []
    for cname in _CLUSTERING:
        g = _cluster_call(cname, log, k)
        if g is None:
            continue
        vals.append(recovery(gt_cases, M.to_case_labels(log, g))["ari"])
    if not vals:
        return float("nan"), float("nan")
    return sum(vals) / len(vals), max(vals)


def experiment_sweeps(quick: bool) -> pd.DataFrame:
    rows = []
    noises = (0.0, 0.05, 0.1, 0.2) if quick else (0.0, 0.05, 0.1, 0.2, 0.3, 0.4)
    sizes = (60, 150) if quick else (100, 300, 1000, 3000)
    builders = {
        "running_example": lambda **kw: running_example_log(**kw),
        "k_view_k4": lambda **kw: k_view_log(k=4, **kw),
    }
    for lg, fn in builders.items():
        base_n = 40 if quick else 180
        for nz in noises:
            if lg == "running_example":
                log, gt, _ = fn(n_cases=6 * base_n, seed=1, noise=nz)
            else:
                log, gt, _ = fn(n_per_view=base_n, seed=1, noise=nz)
            gt_cases = dict(gt)
            k = len(set(gt.values()))
            kap = M.group_kappa(log)
            cmean, cbest = _clustering_ari_stats(log, gt_cases, k)
            rows.append({"log": lg, "sweep": "noise", "value": nz, "method": "kappa",
                         "ari": recovery(gt_cases, M.to_case_labels(log, kap))["ari"],
                         "n_groups": n_groups(kap)})
            rows.append({"log": lg, "sweep": "noise", "value": nz,
                         "method": "clustering_mean", "ari": cmean,
                         "n_groups": float("nan")})
            rows.append({"log": lg, "sweep": "noise", "value": nz,
                         "method": "clustering_best", "ari": cbest,
                         "n_groups": float("nan")})
        for sz in sizes:
            if lg == "running_example":
                log, gt, _ = fn(n_cases=sz, seed=1, noise=0.0)
            else:
                log, gt, _ = fn(n_per_view=max(sz // 4, 4), seed=1, noise=0.0)
            gt_cases = dict(gt)
            k = len(set(gt.values()))
            kap = M.group_kappa(log)
            cmean, cbest = _clustering_ari_stats(log, gt_cases, k)
            rows.append({"log": lg, "sweep": "size", "value": log.n_cases,
                         "method": "kappa",
                         "ari": recovery(gt_cases, M.to_case_labels(log, kap))["ari"],
                         "n_groups": n_groups(kap)})
            rows.append({"log": lg, "sweep": "size", "value": log.n_cases,
                         "method": "clustering_mean", "ari": cmean,
                         "n_groups": float("nan")})
            rows.append({"log": lg, "sweep": "size", "value": log.n_cases,
                         "method": "clustering_best", "ari": cbest,
                         "n_groups": float("nan")})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# E4 -- task-mining case study
# --------------------------------------------------------------------------- #
def experiment_taskmining(quick: bool, translucent: bool) -> pd.DataFrame:
    from tpv.log.synth import helpdesk_gt

    rows = []
    for rework in (False, True):
        n = (24, 18) if quick else (320, 230)
        log, gt, _ = helpdesk_gt(n[0], n[1], seed=1, rework=rework)
        gt_cases = dict(gt)
        views = induce_views(log)
        kap = M.group_kappa(log)
        r = recovery(gt_cases, M.to_case_labels(log, kap))
        # confusion: kappa view label x true role
        conf: Counter = Counter()
        t2v = {t: v.label for v in views for t in v.traces}
        for t in log.trace_set():
            for cid in log.case_ids[t]:
                conf[(t2v[t], gt_cases[cid])] += 1
        q_global = weighted_model_quality([log], mode="mined", translucent=translucent)
        q_kappa = weighted_model_quality([v.sublog for v in views], mode="mined",
                                         translucent=translucent)
        rows.append({
            "log": f"helpdesk{'_rework' if rework else ''}",
            "n_views": len(views), "roles": len(set(gt_cases.values())),
            "ari": r["ari"], "nmi": r.get("nmi", float("nan")),
            "purity": r["purity"],
            "confusion": "; ".join(f"{a}->{b}:{c}" for (a, b), c in sorted(conf.items())),
            "global_precision": round(q_global["precision"], 3),
            "kappa_precision": round(q_kappa["precision"], 3),
            "global_simplicity": round(q_global["simplicity"], 3),
            "kappa_simplicity": round(q_kappa["simplicity"], 3),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# E5 -- scenario-based case study: IT service-desk desktop workflow, noise sweep
# --------------------------------------------------------------------------- #
_CASE_NOISE_QUICK = (0.0, 0.1, 0.2)
# Noise >= 0.3 makes the under-separating @auto clustering baselines merge all
# roles into one sub-log; IMtf then infers a wide AND-block whose translucent
# reachability / alignment-product graph blows past memory (see the caps in
# tpv/vendor/tconf).  The story -- kappa exact at 0, degrading as noise rises,
# the baselines never recovering -- is already fully visible over 0..0.2.
_CASE_NOISE_FULL = (0.0, 0.05, 0.1, 0.15, 0.2)
# ARI is cheap (no model discovery, no alignments), so the partition metrics can
# be swept further than the quality metrics.  This matters because the measured
# error rate of extracting enabled activities from screenshots is far above 0.2:
# ActivityGen [Beyel, Manuel & van der Aalst, ECAI 2024, Tab. 3] reports GUI
# element detection F1 0.33-0.43 on RICO.  Reporting kappa only up to p=0.2
# would understate how far the realistic operating point is.
_CASE_NOISE_ARI_ONLY = (0.3, 0.4)
# The same sweep is repeated under an addition-skewed corruption mix, because
# that paper's precision (0.233) is far below its recall (0.567): the real
# channel invents available actions more often than it misses them.
_CASE_NOISE_MODES = ("balanced", "activitygen")
_Q8 = ["fitness", "precision", "f1", "generalization", "simplicity",
       "translucent_fitness", "translucent_precision", "translucent_f1"]


def _all_groupings(log, gt_cases, attrs, k) -> dict:
    """Every grouping the partition experiment scores: global, kappa, classical /
    translucent variants, and each clustering / attribute family at k=GT and
    k=silhouette.  Returns ``{method_name: grouping}`` (skips unavailable ones)."""
    g = {
        "global": M.group_global(log),
        "kappa": M.group_kappa(log),
        "kappa_supported": M.group_kappa_supported(log),
        "classical_variants": M.group_classical_variants(log),
        "translucent_variants": M.group_translucent_variants(log),
    }
    for cname in _CLUSTERING:
        for suffix, kk in (("@k", k), ("@auto", None)):
            gg = _cluster_call(cname, log, kk)
            if gg is not None:
                g[f"{cname}{suffix}"] = gg
    for aname, afn in M.ATTR_METHODS.items():
        if attrs is None:
            continue
        for suffix, kk in (("@k", k), ("@auto", None)):
            gg = afn(log, attrs, kk)
            if gg is not None:
                g[f"{aname}{suffix}"] = gg
    return g


def experiment_case_study(quick: bool, translucent: bool, seeds: list) -> pd.DataFrame:
    from tpv.log.tasks import task_mining_servicedesk

    noises = _CASE_NOISE_QUICK if quick else _CASE_NOISE_FULL
    # (noise level, corruption mix, whether to score model quality)
    plan = [(nz, "balanced", True) for nz in noises]
    if not quick:
        plan += [(nz, "balanced", False) for nz in _CASE_NOISE_ARI_ONLY]
        plan += [(nz, "activitygen", False)
                 for nz in _CASE_NOISE_FULL[1:] + _CASE_NOISE_ARI_ONLY]
    npr = 40 if quick else 250
    rows = []
    for seed in seeds:
        for nz, nmode, with_quality in plan:
            log, gt, attrs = task_mining_servicedesk(
                npr, seed=1 + seed, noise=nz, noise_mode=nmode)
            noise_report = getattr(log, "noise_report", {})
            score_quality = translucent and with_quality
            gt_cases = dict(gt)
            k = len(set(gt_cases.values()))
            views = induce_views(log)

            def _emit(method, grouping, sublogs, mode, idviews):
                r = recovery(gt_cases, M.to_case_labels(log, grouping)) if grouping \
                    else recovery(gt_cases,
                                  {cid: v.label for v in views for t in v.traces
                                   for cid in log.case_ids[t]})
                q = (weighted_model_quality(sublogs, mode=mode,
                                            translucent=translucent,
                                            identifier_views=idviews)
                     if with_quality else {})
                rows.append({
                    "seed": seed, "noise": nz, "noise_mode": nmode,
                    "realised_noise": noise_report.get("realised", float("nan")),
                    "n_added": noise_report.get("n_added", float("nan")),
                    "n_dropped": noise_report.get("n_dropped", float("nan")),
                    "method": method, "k": k,
                    "n_groups": len(set(grouping.values())) if grouping else len(views),
                    "n_models": len(sublogs),
                    "ari": r["ari"], "nmi": r.get("nmi", float("nan")),
                    "v_measure": r.get("v_measure", float("nan")),
                    # homogeneity says whether a grouping ever mixes hidden labels,
                    # completeness whether it splits one across views: kappa's failure
                    # mode is the second, and Sect. 5.4 quotes the first
                    "homogeneity": r.get("homogeneity", float("nan")),
                    "completeness": r.get("completeness", float("nan")), "purity": r["purity"],
                    **{c: q.get(c, float("nan")) for c in _Q8},
                })

            for name, grp in _all_groupings(log, gt_cases, attrs, k).items():
                _emit(name, grp, M.to_sublogs(log, grp) if score_quality else [],
                      "mined", None)
            if score_quality:
                _emit("kappa_identifier", M.group_kappa(log),
                      [v.sublog for v in views], "identifier", views)
    frame = pd.DataFrame(rows)
    for c in _Q8 + ["ari", "nmi", "v_measure", "purity"]:
        if c in frame:
            frame[c] = frame[c].round(3)
    return frame


# --------------------------------------------------------------------------- #
# aggregation + tex
# --------------------------------------------------------------------------- #
def _logs_overview(quick: bool) -> pd.DataFrame:
    """One row per kept log (KEEP_LOGS order), display names, no events column."""
    by_key = {}
    for name, log, gt, _attrs in build_all(quick, seed=0):
        if name not in KEEP_LOGS:
            continue
        lens = [len(t) for t in log.trace_set() for _ in log.case_ids[t]]
        by_key[name] = {
            "_key": name,
            "log": LOG_DISPLAY.get(name, name.replace("_", r"\_")),
            "cases": log.n_cases,
            "acts": len(log.activities),
            "avg\\ len": f"{sum(lens) / max(len(lens), 1):.1f}",
            "class.\\ var.": len(log.classical_variants()),
            "transl.\\ var.": len(log.trace_set()),
            "hidden $k$": len(set(gt.values())) if gt else "--",
            "$\\kappa$ views": len(induce_views(log)),
        }
    return pd.DataFrame([by_key[k] for k in KEEP_LOGS if k in by_key])


def _logs_overview_tex(df: pd.DataFrame) -> str:
    """Full `tabular` for the log table: a rule before the last column ($\\kappa$
    views is a result) and an italic group-header row before each group."""
    cols = [c for c in df.columns if c != "_key"]
    ncol = len(cols)
    head = " & ".join(cols) + r" \\"
    lines = [r"\begin{tabular}{l" + "r" * (ncol - 2) + "|r}", r"\toprule",
             head, r"\midrule"]
    # The italic group headers spelled out what each family isolates.  In a
    # page-limited paper they cost ten lines to say what the log names and the
    # caption already say, so they stay in the CSV and leave the table.
    # The group headers, and the blank lines that separated them, are gone: the log
    # names and the caption say what each family isolates, and at 13 pages the
    # vertical space is worth more than the grouping.
    for _, row in df.iterrows():
        lines.append(" & ".join(str(row[c]) for c in cols) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(lines)


def _attributes_table(quick: bool) -> pd.DataFrame:
    """Per recorded attribute: kind, type, and mean NMI with the hidden label
    across all ground-truth logs."""
    from collections import defaultdict

    accum: dict = defaultdict(list)
    for _name, _log, gt, attrs in build_all(quick, seed=0):
        if gt is None or attrs is None:
            continue
        for a, v in attribute_informativeness(attrs, dict(gt)).items():
            accum[a].append(v)
    rows = []
    for a, meta in ATTRIBUTE_SCHEMA.items():
        vals = accum.get(a, [])
        nmi = sum(vals) / len(vals) if vals else float("nan")
        rows.append({
            "attribute": a.replace("_", r"\_"),
            "kind": meta["kind"],
            "type": meta["type"],
            "NMI w/ hidden label": round(nmi, 3),
        })
    return pd.DataFrame(rows)


# named look-ups used by _findings_tex
_TABLE_METHODS = [
    "global", "kappa", "kappa_identifier",
    "cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k",
    "attr_clean@k", "attr_noisy@k",
    "classical_variants", "translucent_variants",
]

# canonical row order for the summary tables -- every grouping the experiments score
_QUALITY_ROWS = plots.QUALITY_ROWS

# --------------------------------------------------------------------------- #
# reduced footprint for the paper section (the harness still runs all 12 logs
# and all ~21 groupings; the paper tables are filtered views of that data)
# --------------------------------------------------------------------------- #
KEEP_LOGS = [
    "running_example",
    "k_view_k2", "k_view_k3", "k_view_k4", "k_view_k5",
    "partial_parallel", "enterprise", "hidden_context", "loop_process",
]

# internal name -> display name used in the log table
LOG_DISPLAY = {
    "running_example": "running example",
    "k_view_k2": "$k$-view ($k{=}2$)",
    "k_view_k3": "$k$-view ($k{=}3$)",
    "k_view_k4": "$k$-view ($k{=}4$)",
    "k_view_k5": "$k$-view ($k{=}5$)",
    "partial_parallel": "parallel choices",
    "enterprise": "enterprise",
    "hidden_context": "role split",
    "loop_process": "rework loop",
}

# internal name -> italic group-header line (LaTeX) placed above the group's rows
LOG_GROUP = {
    "running_example": r"\emph{running example -- $L_{\mathrm{run}}$ from the "
                       r"preliminaries at scale; the hidden label offers the two "
                       r"choices concurrently, sequentially, or pinned}",
    "k_view_k2": r"\emph{$k$-view -- one base process, $k$ compositions of three "
                 r"choices; varies the ground-truth $k$}",
    "partial_parallel": r"\emph{parallel choices -- labels differ only in which pair "
                        r"is concurrent; executed sequences are identical}",
    "enterprise": r"\emph{enterprise -- $21$ activities and five roles toggling "
                  r"three review blocks}",
    "hidden_context": r"\emph{role split -- three roles and only six classical "
                      r"variants; the smallest clean case, and the only log in "
                      r"which a label skips activities entirely}",
    "loop_process": r"\emph{rework loop -- no hidden context; $\kappa$ has no loop "
                    r"operator and unrolls the loop}",
}

# every grouping the harness scores, in the order the paper tables list them:
# global, kappa, then each clustering / attribute family at k=GT and k=auto, then
# the two variant groupings
_PAPER_ROWS = [
    "global", "kappa", "kappa_supported",
    "cf_kmeans@k", "cf_kmeans@auto", "cf_ward@k", "cf_ward@auto",
    "ctx_kmeans@k", "ctx_kmeans@auto", "enabled@k", "enabled@auto",
    "trace2vec@k", "trace2vec@auto",
    "attr_clean@k", "attr_clean@auto", "attr_noisy@k", "attr_noisy@auto",
    "attr_all@k", "attr_all@auto",
    "classical_variants", "translucent_variants",
    # separated by a rule in the tables: `role` IS the hidden label, so this row
    # is an upper bound on any method, not a competing baseline.
    "attr_oracle@k",
]

# row labels for the paper tables -- the acronyms coined in the Baselines
# paragraph.  GT = k set to the ground-truth number of views; auto = k by
# silhouette.  (plots.LABEL is still used by the appendix figures.)
PAPER_LABEL = {
    "global": "global",
    "kappa": r"$\kappa$ (ours)",
    "kappa_supported": r"$\kappa$ + support (ours)",
    "cf_kmeans@k": r"CF-TC $k$-means (GT)",
    "cf_kmeans@auto": r"CF-TC $k$-means (auto)",
    "cf_ward@k": r"CF-TC Ward (GT)",
    "cf_ward@auto": r"CF-TC Ward (auto)",
    "ctx_kmeans@k": r"CTX-TC (GT)",
    "ctx_kmeans@auto": r"CTX-TC (auto)",
    "enabled@k": r"EN-TC (GT)",
    "enabled@auto": r"EN-TC (auto)",
    "trace2vec@k": r"D2V-TC (GT)",
    "trace2vec@auto": r"D2V-TC (auto)",
    "attr_clean@k": r"ATTR-TC clean (GT)",
    "attr_clean@auto": r"ATTR-TC clean (auto)",
    "attr_noisy@k": r"ATTR-TC noisy (GT)",
    "attr_noisy@auto": r"ATTR-TC noisy (auto)",
    "attr_all@k": r"ATTR-TC all (GT)",
    "attr_all@auto": r"ATTR-TC all (auto)",
    "classical_variants": "variant discovery",
    "translucent_variants": "translucent-variant grouping",
    "attr_oracle@k": r"ATTR-TC oracle (GT)$^{\dagger}$",
    "attr_oracle@auto": r"ATTR-TC oracle (auto)$^{\dagger}$",
}

# rows that are upper bounds rather than competitors -- excluded from "best in
# column" bolding so they cannot steal a bold from an actual baseline.
_ORACLE_ROWS = {"attr_oracle@k", "attr_oracle@auto"}


# derived-column fallback for older e2_quality.csv files without f1 columns
def _ensure_f1_cols(e2: pd.DataFrame) -> pd.DataFrame:
    e2 = e2.copy()
    if "f1" not in e2 and {"fitness", "precision"} <= set(e2.columns):
        e2["f1"] = [harmonic_f1(f, p) for f, p in zip(e2["fitness"], e2["precision"])]
    if "translucent_f1" not in e2 and \
            {"translucent_fitness", "translucent_precision"} <= set(e2.columns):
        e2["translucent_f1"] = [harmonic_f1(f, p) for f, p in
                                zip(e2["translucent_fitness"], e2["translucent_precision"])]
    return e2


#: Table 2 shows the GT runs, like Tables 3 and 4; the silhouette-chosen runs are
#: quoted in the prose and kept in the result CSVs
_PARTITION_ROWS_PAPER = None      # set below, after _PAPER_ROWS


def _summary_partition(e1: pd.DataFrame) -> pd.DataFrame:
    e1 = e1[e1["log"].isin(KEEP_LOGS)]
    g1 = e1.groupby("method").agg(
        ARI=("ari", "mean"),
        NMI=("nmi", "mean"),
        purity=("purity", "mean"),
        enabl_sig=("sig_per_variant", "mean"),
    )
    rows = [m for m in _PARTITION_ROWS_PAPER if m in g1.index]
    out = g1.reindex(rows).round(3)
    out.columns = ["ARI", "NMI", "purity", r"enabl.\ sig."]
    return out


# (e2 column, display header) for the model-quality table -- every computed metric
_QUALITY_COLS = [
    # `#mdl` is back: the prose quotes the group counts of variant discovery and
    # translucent-variant grouping, and without this column the reader cannot
    # check them.  `fitness` is gone: IMtf is fitness-preserving on the sub-log
    # it is given, so the column was 1.000 in every row, which also made F1 a
    # monotone function of precision.  It is stated once in the prose instead.
    ("n_models", r"\#mdl"),
    ("precision", "prec."),
    ("f1", "F1"),
    ("generalization", "gen."),
    ("simplicity", "simp."),
    ("translucent_fitness", r"tr.\ fit."),
    ("translucent_precision", r"tr.\ prec."),
    ("translucent_f1", r"tr.\ F1"),
]


#: model quality is reported for k = ground truth only; the silhouette variants
#: differ by a few thousandths and cost nine rows
#: Two rows the tables do not need: CF-TC k-means is the weaker of the two CF-TC
#: linkages, and ATTR-TC "all" lies between the clean and the noisy attributes on
#: every measure.  Both stay in the result CSVs; at 13 pages the tables show the
#: variant that carries the argument.
_DISPLAY_DROP = {"cf_kmeans@k", "cf_kmeans@auto", "attr_all@k", "attr_all@auto"}
_QUALITY_ROWS_PAPER = [m for m in _PAPER_ROWS
                       if not m.endswith("@auto") and m not in _DISPLAY_DROP]
_PARTITION_ROWS_PAPER = _QUALITY_ROWS_PAPER


def _summary_quality(e2: pd.DataFrame, *, case_weighted: bool) -> pd.DataFrame:
    e2 = _ensure_f1_cols(e2)
    e2 = e2[e2["log"].isin(KEEP_LOGS)]
    cols = [c for c, _ in _QUALITY_COLS if c in e2.columns]
    if case_weighted and "n_cases" in e2.columns:
        def _agg(d):
            w = d["n_cases"].to_numpy(dtype=float)
            return pd.Series({c: float(np.average(d[c].to_numpy(dtype=float), weights=w))
                              for c in cols})
        g = e2.groupby("method").apply(_agg)
    else:
        g = e2.groupby("method")[cols].mean()
    rows = [m for m in _QUALITY_ROWS_PAPER if m in g.index]
    out = g.reindex(rows).round(3)
    out.columns = [h for c, h in _QUALITY_COLS if c in cols]
    return out


# --------------------------------------------------------------------------- #
# numbers.tex -- every figure Section 5's prose quotes, as LaTeX macros
#
# Rationale: findings.tex has always been generated but is \input nowhere, so
# every number in the evaluation prose was typed by hand.  That is how the
# submitted PDF came to say "1.24 enabled-activity signatures" while its own
# Table 2 said 1.185, and "325 and 368 groups" from a different run than the
# tables.  These macros are derived from the *same* summary frames that build
# the tables, so prose and tables cannot disagree; and a macro whose experiment
# did not run becomes a LaTeX error rather than a stale number.
# --------------------------------------------------------------------------- #
_TC_AT_GT = ["cf_kmeans@k", "cf_ward@k", "ctx_kmeans@k", "enabled@k", "trace2vec@k"]
_TC_AT_AUTO = [m.replace("@k", "@auto") for m in _TC_AT_GT]

# LaTeX macro names cannot contain digits, so each swept noise level gets a
# spelled-out suffix.  Keyed by value, never by position in the sweep.
_NOISE_MACRO_NAME = {
    0.0: "Zero", 0.05: "Five", 0.1: "Ten", 0.15: "Fifteen",
    0.2: "Twenty", 0.3: "Thirty", 0.4: "Forty",
}


def _macros_tex(e1: pd.DataFrame, e2: pd.DataFrame, e5: "pd.DataFrame | None",
                quick: bool = False) -> str:
    part = _summary_partition(e1)          # exactly Table 2 (GT rows)
    # the silhouette-chosen runs are no longer printed, but the prose still
    # quotes them, so macros come from the full frame, not from the table
    global _PARTITION_ROWS_PAPER
    _all_rows, _PARTITION_ROWS_PAPER = _PARTITION_ROWS_PAPER, _PAPER_ROWS
    part_all = _summary_partition(e1)
    _PARTITION_ROWS_PAPER = _all_rows
    qual = _summary_quality(e2, case_weighted=False)   # exactly Table 3
    macros: "dict[str, str]" = {}
    # A --quick run produces the same macro names with smoke-test values.  Stamp
    # the provenance so a placeholder can never sit unnoticed in the paper: the
    # LaTeX side turns this into a visible banner.
    macros["numbersAreQuickRun"] = "yes" if quick else "no"
    macros["numbersSeeds"] = str(int(e1["seed"].nunique())) if "seed" in e1 else "?"
    macros["numbersLogs"] = str(len([k for k in KEEP_LOGS if k in set(e1["log"])]))

    def put(name: str, value, fmt: str = "%.2f") -> None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return
        macros[name] = (fmt % value) if isinstance(value, float) else str(value)

    def cell(df, row, col):
        if row in df.index and col in df.columns:
            v = df.loc[row, col]
            return float(v) if pd.notna(v) else None
        return None

    def best(df, rows, col, how="max"):
        vals = [v for v in (cell(df, r, col) for r in rows) if v is not None]
        if not vals:
            return None
        return max(vals) if how == "max" else min(vals)

    # -- Section 5.2, recovery ------------------------------------------------
    put("kapARI", cell(part, "kappa", "ARI"))
    put("kapNMI", cell(part, "kappa", "NMI"))
    put("kapPurity", cell(part, "kappa", "purity"))
    put("kapSig", cell(part, "kappa", r"enabl.\ sig."))
    put("supARI", cell(part, "kappa_supported", "ARI"))
    put("supPurity", cell(part, "kappa_supported", "purity"))
    put("varSig", cell(part, "classical_variants", r"enabl.\ sig."))
    put("tvarSig", cell(part, "translucent_variants", r"enabl.\ sig."))
    put("tcBestARIgt", best(part, _TC_AT_GT, "ARI"))
    put("tcBestARIauto", best(part_all, _TC_AT_AUTO, "ARI"))
    put("attrCleanARI", cell(part, "attr_clean@k", "ARI"))
    put("attrNoisyARI", cell(part, "attr_noisy@k", "ARI"))
    put("attrNoisyNMI", cell(part, "attr_noisy@k", "NMI"))
    put("attrOracleARI", cell(part, "attr_oracle@k", "ARI"))
    put("hiddenKmax", int(e1["k"].max()), fmt="%d")

    # group counts: quoted in the prose, so they must come from the same frame
    put("varGroups", cell(qual, "classical_variants", r"\#mdl"), fmt="%.0f")
    put("tvarGroups", cell(qual, "translucent_variants", r"\#mdl"), fmt="%.0f")
    put("kapGroups", cell(qual, "kappa", r"\#mdl"), fmt="%.1f")

    # -- Section 5.3, model quality -------------------------------------------
    for key, row in (("kap", "kappa"), ("glob", "global"),
                     ("var", "classical_variants"), ("tvar", "translucent_variants"),
                     ("attrClean", "attr_clean@k"), ("attrCleanAuto", "attr_clean@auto"),
                     ("attrOracle", "attr_oracle@k")):
        put(key + "Prec", cell(qual, row, "prec."))
        put(key + "FOne", cell(qual, row, "F1"))
        put(key + "Gen", cell(qual, row, "gen."))
        put(key + "Simp", cell(qual, row, "simp."))
        put(key + "TrFit", cell(qual, row, r"tr.\ fit."))
        put(key + "TrPrec", cell(qual, row, r"tr.\ prec."))
        put(key + "TrFOne", cell(qual, row, r"tr.\ F1"))

    # worst generalisation among the two variant-grouping rows -- the paper
    # claimed variant discovery was worst when translucent-variant grouping is
    put("worstGen", best(qual, ["classical_variants", "translucent_variants"],
                         "gen.", how="min"))
    put("tcGenTypical",
        float(np.nanmean([v for v in (cell(qual, r, "gen.") for r in _TC_AT_GT)
                          if v is not None])))

    # -- Section 5.4, case study ----------------------------------------------
    if e5 is not None and not e5.empty:
        # the ActivityGen-skewed sweep is reported separately; never mix the two
        if "noise_mode" in e5.columns:
            e5_ag = e5[e5.noise_mode == "activitygen"]
            ag = e5_ag[e5_ag.method == "kappa"].groupby("noise")["ari"].mean()
            for nz in ag.index:
                nm = _NOISE_MACRO_NAME.get(round(float(nz), 3))
                if nm is not None:
                    put(f"caseAgKapARI{nm}", float(ag.loc[nz]))
            # The meaningful statement is "the realised rate matches the
            # requested one", so report the worst deviation across the sweep.
            # A mean of the realised rates would just be a mean of the swept
            # levels and would say nothing about whether they match.
            rn = (e5.groupby(["noise_mode", "noise"])["realised_noise"].mean()
                  .reset_index())
            rn["dev"] = (rn["realised_noise"] - rn["noise"]).abs()
            for mode, nm in (("balanced", "Bal"), ("activitygen", "Ag")):
                sel = rn[rn.noise_mode == mode]
                if not sel.empty and sel["dev"].notna().any():
                    put(f"realisedNoiseDev{nm}", float(sel["dev"].max()), fmt="%.3f")
            adds = e5[e5.method == "kappa"].groupby("noise_mode")[
                ["n_added", "n_dropped"]].mean()
            for mode, nm in (("balanced", "Bal"), ("activitygen", "Ag")):
                if mode in adds.index:
                    a, d = adds.loc[mode, "n_added"], adds.loc[mode, "n_dropped"]
                    if pd.notna(a) and pd.notna(d) and (a + d) > 0:
                        put(f"addShare{nm}", float(a / (a + d)))
        e5 = _only_mode(e5)
        noises = sorted(e5.noise.unique())
        k5 = e5[e5.method == "kappa"].groupby("noise")
        ari5, grp5 = k5["ari"].mean(), k5["n_groups"].mean()
        s5 = e5[e5.method == "kappa_supported"].groupby("noise")
        sari5, sgrp5 = s5["ari"].mean(), s5["n_groups"].mean()
        # Sect. 5.4 claims kappa never mixes roles under noise: quote the weakest
        # homogeneity it reaches over the swept levels, not a typed 1.00
        if "homogeneity" in e5:
            # only the levels Table 3 shows; 0.3 and 0.4 are swept for ARI alone
            shown = max(_CASE_NOISE_FULL)
            k5h = e5[(e5.method == "kappa") & (e5.noise <= shown)]
            hom = k5h.groupby("noise")["homogeneity"].mean()
            if len(hom):
                put("caseKapHom", float(hom.min()), fmt="%.2f")
            com = k5h.groupby("noise")["completeness"].mean()
            if len(com):
                put("caseKapCompl", float(com.min()), fmt="%.2f")
        for nz in noises:
            # name the macro after the noise *value*, not its position in the
            # sweep -- a positional map silently mislabels every macro as soon
            # as the swept levels change
            nm = _NOISE_MACRO_NAME.get(round(float(nz), 3))
            if nm is None or nz not in ari5.index:
                continue
            put(f"caseKapARI{nm}", float(ari5.loc[nz]))
            put(f"caseKapViews{nm}", float(grp5.loc[nz]), fmt="%.0f")
            if nz in sari5.index:
                put(f"caseSupARI{nm}", float(sari5.loc[nz]))
                put(f"caseSupViews{nm}", float(sgrp5.loc[nz]), fmt="%.0f")
        cs = _case_summary(e5)
        gt_cols = [c for c in cs.columns if c.startswith("ARI ")]
        tc_vals = [cell(cs, r, c) for r in _TC_AT_GT for c in gt_cols]
        tc_vals = [v for v in tc_vals if v is not None]
        if tc_vals:
            put("caseTCARIlo", min(tc_vals))
            put("caseTCARIhi", max(tc_vals))
        auto_vals = [cell(cs, r, c) for r in _TC_AT_AUTO for c in gt_cols]
        auto_vals = [v for v in auto_vals if v is not None]
        if auto_vals:
            put("caseTCautoARIlo", min(auto_vals))
        put("caseNoiseMax", max(noises), fmt="%g")
        put("caseNoiseLevels", len(noises), fmt="%d")

    head = (
        "% AUTOGENERATED by evaluation/run_evaluation.py -- do not edit.\n"
        "% Regenerate with:\n"
        "%   venv/Scripts/python evaluation/run_evaluation.py --full \\\n"
        "%       --paper-out <overleaf>/tables\n"
        "% Every number Section 5 quotes lives here, derived from the same\n"
        "% frames as Tables 2-4, so prose and tables cannot drift apart.\n"
    )
    body = "".join(rf"\newcommand{{\{k}}}{{{v}}}" + "\n"
                   for k, v in sorted(macros.items()))
    return head + body


def _findings_tex(e1: pd.DataFrame, e2: pd.DataFrame, e3: pd.DataFrame,
                  e4: pd.DataFrame) -> str:
    gt = e1.dropna(subset=["ari"])
    kap = gt[gt.method == "kappa"]
    cl = gt[gt.method == "classical_variants"]
    tv = gt[gt.method == "translucent_variants"]
    ratio_cl = (cl.set_index(["log", "seed"])["n_groups"]
                / kap.set_index(["log", "seed"])["n_groups"]).mean()
    ratio_tv = (tv.set_index(["log", "seed"])["n_groups"]
                / kap.set_index(["log", "seed"])["n_groups"]).mean()
    e2 = _ensure_f1_cols(e2)
    q = e2.groupby("method")[["fitness", "precision", "f1", "simplicity",
                              "generalization", "n_models"]].mean()
    qcw = None
    if "n_cases" in e2.columns:
        def _cw(d):
            w = d["n_cases"].to_numpy(dtype=float)
            return pd.Series({c: float(np.average(d[c].to_numpy(dtype=float), weights=w))
                              for c in ("f1", "translucent_f1")
                              if c in d.columns})
        qcw = e2.groupby("method").apply(_cw)

    def _m(name):
        s = gt[gt.method == name]
        return s["ari"].mean() if not s.empty else float("nan")

    # k=GT trace-clustering baselines (control flow / context / trace2vec / enabled)
    cf_at_k = [m for m in ("cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k")]
    cf_ari = gt[gt.method.isin(cf_at_k)]["ari"].mean()
    cf_best = max((_m(m) for m in cf_at_k), default=float("nan"))
    ac, an_, aa, en = _m("attr_clean@k"), _m("attr_noisy@k"), _m("attr_all@k"), _m("enabled@k")

    tq = (e2.groupby("method")[["translucent_precision", "translucent_fitness",
                                "translucent_f1"]].mean()
          if "translucent_precision" in e2 else None)

    lines = [
        r"\item \textbf{RQ1 (separation).} A single global model yields one group "
        rf"(mean frequency-weighted precision {q.loc['global','precision']:.2f}) versus a "
        rf"hidden $k$ of up to {int(e1['k'].max())}. Classical-variant grouping produces "
        rf"{ratio_cl:.0f}$\times$ more groups than $\kappa$ and still mixes "
        rf"{cl['sig_per_variant'].mean():.2f} distinct enabled-activity signatures per "
        rf"(group, variant) (versus {kap['sig_per_variant'].mean():.2f} for $\kappa$); "
        rf"exact translucent-variant grouping produces {ratio_tv:.0f}$\times$ more.",
        r"\item \textbf{RQ1 (recovery).} $\kappa$ recovers the hidden context with mean ARI "
        rf"{kap['ari'].mean():.2f} (NMI {kap['nmi'].mean():.2f}, purity "
        rf"{kap['purity'].mean():.2f}) and exactly $k$ views, using no cluster count, distance "
        rf"function, or threshold. Trace clustering \emph{{given}} $k=\mathrm{{GT}}$ reaches at "
        rf"most ARI {cf_ari:.2f} on average ({cf_best:.2f} for the best of the four); "
        rf"classical- and translucent-variant grouping reach ARI {cl['ari'].mean():.2f} / "
        rf"{tv['ari'].mean():.2f}.",
        r"\item \textbf{RQ2 (model quality).} Per-family means: $\kappa$'s per-view models "
        rf"attain fitness {q.loc['kappa','fitness']:.2f} / precision "
        rf"{q.loc['kappa','precision']:.2f} / F1 {q.loc['kappa','f1']:.2f} with "
        rf"{q.loc['kappa','n_models']:.1f} models"
        + (rf" (translucent F1 {tq.loc['kappa','translucent_f1']:.2f})" if tq is not None else "")
        + rf", versus classic F1 {q.loc['global','f1']:.2f} for the single global model and "
        rf"{q.loc['classical_variants','f1']:.2f} at "
        rf"{q.loc['classical_variants','n_models']:.0f} models for variant discovery"
        + (rf"; the global and variant-discovery models reach translucent F1 only "
           rf"{tq.loc['global','translucent_f1']:.2f} / "
           rf"{tq.loc['classical_variants','translucent_f1']:.2f}" if tq is not None else "")
        + "."
        + (rf" Case-weighted (dominated by the two \emph{{enterprise}} logs, "
           rf"$\approx$$37\%$ of cases), $\kappa$'s classic / translucent F1 are "
           rf"{qcw.loc['kappa','f1']:.2f} / {qcw.loc['kappa','translucent_f1']:.2f} versus "
           rf"{qcw.loc['global','f1']:.2f} / {qcw.loc['global','translucent_f1']:.2f} for "
           rf"\emph{{global}}." if (qcw is not None and tq is not None
                                    and "translucent_f1" in qcw.columns) else ""),
    ]

    nz = e3[e3["sweep"] == "noise"]
    if not nz.empty:
        kap_n = nz[nz.method == "kappa"]
        cm = nz[nz.method == "clustering_mean"]
        a0 = kap_n[kap_n["value"] == 0.0]["ari"].mean()
        hi = kap_n["value"].max()
        a_hi = kap_n[kap_n["value"] == hi]["ari"].mean()
        g0 = kap_n[kap_n["value"] == 0.0]["n_groups"].mean()
        g_hi = kap_n[kap_n["value"] == hi]["n_groups"].max()
        cm_mean = cm["ari"].mean()
        lines.append(
            r"\item \textbf{RQ3 (enabled-set noise).} $\kappa$ is exact at zero noise "
            rf"(ARI {a0:.2f}, {g0:.0f} views) but degrades sharply as the enabled sets are "
            rf"perturbed: by noise level {hi:g} its ARI is {a_hi:.2f} and its view count has "
            rf"risen to {g_hi:.0f}. Control-flow trace clustering is insensitive to this noise "
            rf"(mean ARI {cm_mean:.2f} across all levels) but never recovers the context. "
            r"Enabled-set fidelity is thus a precondition for $\kappa$ (see Threats to Validity)."
        )
    if ac == ac:
        lines.append(
            r"\item \textbf{RQ3 (recorded context).} If the view-defining context is recorded "
            rf"as a \emph{{clean}} case attribute \emph{{and}} $k$ is known, attribute clustering "
            rf"also reaches ARI {ac:.2f}; on the \emph{{noisy}} attributes it is at chance "
            rf"(ARI {an_:.2f}), and on clean$+$noisy it drops to {aa:.2f}. Clustering on enabled "
            rf"activities alone reaches ARI {en:.2f}. $\kappa$ needs neither a recorded "
            rf"attribute nor $k$ and still reaches ARI {kap['ari'].mean():.2f}."
        )
    if not e4.empty:
        lines.append(
            r"\item \textbf{Case study.} On the synthetic task-mining helpdesk log $\kappa$ "
            rf"separates the {int(e4.iloc[0]['roles'])} hidden roles with ARI "
            rf"{e4.iloc[0]['ari']:.2f}; the supervisor view exposes the privileged "
            r"\texttt{escalate} / \texttt{approve\_refund} actions absent from the agent view."
        )
    return "\\begin{itemize}\n" + "\n".join(lines) + "\n\\end{itemize}\n"


_CASE_CF = ["cf_kmeans@k", "cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k"]


def _only_mode(e5: pd.DataFrame, mode: str = "balanced") -> pd.DataFrame:
    """E5 now sweeps two corruption mixes; never average across them."""
    if e5 is None or e5.empty or "noise_mode" not in e5.columns:
        return e5
    return e5[e5.noise_mode == mode]


def _case_summary(e5: pd.DataFrame, mode: str = "balanced") -> pd.DataFrame:
    """Rows = every grouping, columns = {ARI, transl. F1} x noise level.

    Only the levels that carry both metrics are shown.  The ARI-only levels are
    swept and reported in the prose, but printing them here would add columns
    that are half empty to an already wide table.
    """
    e5 = _only_mode(e5, mode)
    show = [nz for nz in sorted(e5.noise.unique())
            if e5[(e5.noise == nz)]["translucent_f1"].notna().any()]
    metrics = (("ari", "ARI"), ("translucent_f1", r"tr.\ F1"))
    g = (e5[e5.noise.isin(show)]
         .groupby(["method", "noise"])[[c for c, _ in metrics]].mean())
    out = pd.DataFrame(index=[m for m in _QUALITY_ROWS_PAPER
                              if m in e5.method.unique()])
    for nz in show:
        for col, hdr in metrics:
            vals = [g.loc[(m, nz), col] if (m, nz) in g.index else float("nan")
                    for m in out.index]
            # The highest noise levels are swept for ARI only (model quality is
            # the expensive half), so their translucent-F1 column would be
            # entirely empty.  An all-dashes column is not information.
            if all(pd.isna(v) for v in vals):
                continue
            out[rf"{hdr} $p{{=}}{nz:g}$"] = vals
    return out.round(3)


def _case_findings_tex(e5: pd.DataFrame) -> str:
    if e5 is None or e5.empty:
        return "\\begin{itemize}\n\\item (case study not run)\n\\end{itemize}\n"
    e5 = _only_mode(e5)
    m = e5.groupby(["method", "noise"]).mean(numeric_only=True)
    noises = sorted(e5.noise.unique())
    hi = noises[-1]

    def val(method, nz, col):
        return m.loc[(method, nz), col] if (method, nz) in m.index else float("nan")

    kap0 = val("kappa", 0.0, "ari")
    kg0 = val("kappa", 0.0, "n_groups")
    cf_by_nz = {nz: e5[(e5.method.isin(_CASE_CF)) & (e5.noise == nz)]["ari"].mean()
                for nz in noises}
    # first noise level where the clustering mean beats kappa
    cross = next((nz for nz in noises if nz > 0
                  and cf_by_nz[nz] > val("kappa", nz, "ari")), None)
    L = [
        r"\item \textbf{Scenario.} A synthetic IT service-desk desktop workflow with four "
        r"hidden roles (L1 agent, L2 senior, L3 specialist, supervisor) that differ in which "
        r"triage / diagnosis blocks run in parallel, which steps are skipped, and which "
        r"gated UI actions (\texttt{escalate}, \texttt{approve}, \texttt{force\_close}) are on "
        r"screen; enabled activities come from screenshots, so recordings carry noise.",
        rf"\item \textbf{{$\kappa$ at zero noise.}} $\kappa$ recovers all four roles exactly "
        rf"(ARI {kap0:.2f}, {kg0:.0f} views) with no cluster count, distance, or threshold; "
        rf"each induced identifier is one role (the supervisor view exposes \texttt{{approve}} / "
        rf"\texttt{{force\_close}}, absent from the agent view).",
        rf"\item \textbf{{$\kappa$ under noise.}} Its ARI falls to "
        + ", ".join(rf"{val('kappa',nz,'ari'):.2f} at {nz*100:.0f}\%"
                    for nz in noises if nz > 0)
        + rf"; its view count rises from {kg0:.0f} to "
        rf"{val('kappa',hi,'n_groups'):.0f} --- each corrupted trace becomes its own view.",
    ]
    if cross is not None:
        L.append(rf"\item \textbf{{Crossover.}} The control-flow clustering baseline "
                 rf"(mean of five, $k=\mathrm{{GT}}$) overtakes $\kappa$ on ARI at the first "
                 rf"non-zero noise step ($\approx${cross:g}); it is otherwise flat "
                 rf"(ARI {min(cf_by_nz.values()):.2f}--{max(cf_by_nz.values()):.2f} across all "
                 rf"levels) and never recovers the roles.")
    else:
        L.append(rf"\item \textbf{{Clustering baseline.}} Control-flow clustering "
                 rf"($k=\mathrm{{GT}}$) is noise-insensitive (ARI "
                 rf"{min(cf_by_nz.values()):.2f}--{max(cf_by_nz.values()):.2f}) but never "
                 rf"recovers the roles at any noise level.")
    L += [
        rf"\item \textbf{{Recorded role attribute.}} Clustering on the \emph{{clean}} case "
        rf"attributes (which include \texttt{{role}}) stays at ARI "
        rf"{e5[(e5.method=='attr_clean@k')].groupby('noise')['ari'].mean().min():.2f}--"
        rf"{e5[(e5.method=='attr_clean@k')].groupby('noise')['ari'].mean().max():.2f} at every "
        rf"noise level --- the role label survives enabled-set noise, but the analyst must "
        rf"have recorded it and must supply $k$. $\kappa$ needs neither.",
        rf"\item \textbf{{Enabled-only clustering.}} $k$-means on enabled-activity features "
        rf"is erratic under noise (ARI "
        rf"{e5[(e5.method=='enabled@k')].groupby('noise')['ari'].mean().min():.2f}--"
        rf"{e5[(e5.method=='enabled@k')].groupby('noise')['ari'].mean().max():.2f}) and does "
        rf"not track $\kappa$.",
        rf"\item \textbf{{Variant grouping.}} Classical- and translucent-variant grouping "
        rf"reach ARI $\le${max(val('classical_variants',0.0,'ari'), val('translucent_variants',0.0,'ari')):.2f} "
        rf"even at zero noise (they over-separate into "
        rf"{val('classical_variants',0.0,'n_groups'):.0f}+ groups) and are unaffected by noise.",
        r"\item \textbf{Global model.} One model over the whole log yields a single group "
        rf"(ARI 0) at every noise level.",
        rf"\item \textbf{{Fitness.}} Every approach's per-group models replay their own "
        rf"sub-logs exactly (fitness $=1.00$ throughout), so the classic axes reduce to "
        rf"precision / F1.",
        rf"\item \textbf{{Translucent fitness.}} At zero noise $\kappa$'s per-view models "
        rf"reach translucent fitness {val('kappa',0.0,'translucent_fitness'):.2f} "
        rf"(translucent F1 {val('kappa',0.0,'translucent_f1'):.2f}), the best of all "
        rf"approaches; the single global model is the weakest "
        rf"({val('global',0.0,'translucent_fitness'):.2f}).",
        rf"\item \textbf{{Model quality vs.\ noise.}} As noise rises $\kappa$'s translucent "
        rf"fitness falls to {val('kappa',hi,'translucent_fitness'):.2f} (its views are now "
        rf"noise fragments); the clustering baselines' model quality is roughly flat because "
        rf"their partitions barely change.",
        rf"\item \textbf{{Generalisation.}} Variant grouping generalises worst "
        rf"($\approx${val('classical_variants',0.0,'generalization'):.2f}) --- one trace per "
        rf"model; $\kappa$ and the clustering baselines are $\approx0.9$.",
        rf"\item \textbf{{Precision / F1.}} With fitness pinned at $1$, F1 tracks precision. "
        rf"At zero noise $\kappa$, variant grouping and every $k=\mathrm{{GT}}$ clustering "
        rf"baseline sit at precision {val('kappa',0.0,'precision'):.2f}; as noise rises "
        rf"$\kappa$ holds "
        rf"{min(val('kappa',nz,'precision') for nz in noises if nz>0):.2f}--"
        rf"{max(val('kappa',nz,'precision') for nz in noises if nz>0):.2f} while the "
        rf"control-flow baselines fall to {val('cf_ward@k',hi,'precision'):.2f} "
        rf"(their sub-logs now mix roles).",
        r"\item \textbf{Takeaway.} When the enabled sets are trustworthy $\kappa$ recovers the "
        r"roles exactly and parameter-free and its per-view models are the most faithful to "
        r"the enabled behaviour; once the screenshots are noisy $\kappa$ over-segments and "
        r"loses that edge, while the other approaches --- noise-insensitive but never "
        r"accurate --- still do not recover the roles. Robustness to enabled-set noise is the "
        r"open problem.",
    ]
    return "\\begin{itemize}\n" + "\n".join(L[:15]) + "\n\\end{itemize}\n"


# per-column "best" direction for the paper result tables; "#mdl" / "fit." get no
# emphasis (fitness is constant, model count is not a quality)
_BEST = {
    "ARI": "max", "NMI": "max", "purity": "max", r"enabl.\ sig.": "min",
    "prec.": "max", "F1": "max", "gen.": "max", "simp.": "max",
    r"tr.\ fit.": "max", r"tr.\ prec.": "max", r"tr.\ F1": "max",
}


def _col_direction(col: str) -> "str | None":
    if col in _BEST:
        return _BEST[col]
    if col.startswith("ARI ") or col.startswith(r"tr.\ F1 "):  # case-study columns
        return "max"
    return None


def _bold_best(df: pd.DataFrame) -> pd.DataFrame:
    """Return a string DataFrame: each cell as ``%.3f``; per column, the cell(s)
    equal (at 3 dp) to the column's best value are wrapped in ``\\textbf{...}``.
    NaN renders as ``--``.  Columns with no defined direction are left plain.

    Rows in ``_ORACLE_ROWS`` are upper bounds, not competing baselines, so they
    are excluded when computing the column best -- otherwise the oracle takes
    every bold and the comparison between real methods becomes invisible.  Call
    with method keys as the index and relabel afterwards.
    """
    out = pd.DataFrame(index=df.index)
    competitors = ~df.index.isin(_ORACLE_ROWS)
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce")
        direction = _col_direction(col)
        best = None
        cmp_s = s[competitors]
        if direction is not None and cmp_s.notna().any():
            best = round(cmp_s.max() if direction == "max" else cmp_s.min(), 3)

        def _fmt(v, is_oracle):
            if pd.isna(v):
                return "--"
            txt = f"{v:.3f}"
            # An oracle row is never bolded, not even when it ties the best
            # competitor: it is not in the competition, and a bold there reads
            # as if it had won.
            if is_oracle or best is None or round(v, 3) != best:
                return txt
            return rf"\textbf{{{txt}}}"

        out[col] = [_fmt(v, idx in _ORACLE_ROWS) for idx, v in zip(df.index, s)]
    return out


def _summary_combined(e1: pd.DataFrame, e2: pd.DataFrame) -> pd.DataFrame:
    """Recovery and model quality in one table.

    Both halves are indexed by the same grouping methods, so two floats with
    identical row labels cost a page for nothing.
    """
    part = _summary_partition(e1)
    qual = _summary_quality(e2, case_weighted=False)
    rows = [m for m in _QUALITY_ROWS_PAPER if m in part.index or m in qual.index]
    out = part.reindex(rows).join(qual.reindex(rows), how="outer")
    return out.reindex(rows)


def _write_tables(out: Path, quick: bool, e1, e2, e3, e4, e5=None, attr_df=None) -> None:
    # reduced 9-log table: rule before the last column ("kappa views" is a result,
    # not a log statistic) and an italic group-header per family stating its purpose
    (out / "logs_overview_table.tex").write_text(
        _logs_overview_tex(_logs_overview(quick)), encoding="utf-8")
    at = attr_df if attr_df is not None else _attributes_table(quick)
    (out / "attributes_table.tex").write_text(
        at.to_latex(index=False, escape=False, column_format="lllr",
                    float_format="%.3f"), encoding="utf-8")

    def _relabel(df):
        df = df.copy()
        df.index = pd.Index([PAPER_LABEL.get(m, plots.LABEL.get(m, m)).replace("\n", " ")
                             for m in df.index])
        return df

    def _emit(df, name):
        # bold first (needs the method keys to spot the oracle rows), relabel after
        (out / name).write_text(
            _relabel(_bold_best(df)).to_latex(
                escape=False, na_rep="--",
                column_format="l" + "r" * df.shape[1]),
            encoding="utf-8")

    part = _summary_partition(e1)
    qual = _summary_quality(e2, case_weighted=False)
    qual_cw = _summary_quality(e2, case_weighted=True)
    _emit(part, "summary_partition_table.tex")
    _emit(_summary_combined(e1, e2), "summary_combined_table.tex")
    _emit(qual, "summary_quality_table.tex")
    _emit(qual_cw, "summary_quality_caseweighted_table.tex")
    part.join(qual, how="outer").to_csv(out / "summary.csv")
    (out / "findings.tex").write_text(_findings_tex(e1, e2, e3, e4), encoding="utf-8")

    if e5 is not None and not e5.empty:
        _emit(_case_summary(e5), "case_study_table.tex")
        (out / "findings_case.tex").write_text(_case_findings_tex(e5), encoding="utf-8")
    (out / "numbers.tex").write_text(_macros_tex(e1, e2, e5, quick=quick),
                                     encoding="utf-8")


# files the paper \input's -- copied verbatim by --paper-out so that no manual
# step can leave the Overleaf project holding an older run's tables
PAPER_FILES = (
    "logs_overview_table.tex",
    "summary_partition_table.tex",
    "summary_quality_table.tex",
    "summary_combined_table.tex",
    "case_study_table.tex",
    "numbers.tex",
)


def rebuild_tables(out: Path, paper_out: "Path | None" = None,
                   quick: bool = False) -> dict:
    """Regenerate every table and macro file from the checkpointed CSVs.

    ``run()`` writes each experiment's CSV as soon as it finishes, so the
    expensive part of a run is recoverable.  This re-derives all presentation
    from those CSVs without recomputing anything -- useful after changing how a
    table is laid out, and necessary when the harness was edited while a long
    run was already in flight (Python had already imported the old module).
    """
    out = Path(out)
    frames = {}
    for key, name in (("e1", "e1_separation"), ("e2", "e2_quality"),
                      ("e3", "e3_sweeps"), ("e4", "e4_taskmining"),
                      ("e5", "e5_case_study")):
        p = out / f"{name}.csv"
        if not p.exists():
            raise SystemExit(f"missing {p}; run the experiments first")
        frames[key] = pd.read_csv(p)
    attr_df = _attributes_table(quick)
    _write_tables(out, quick, frames["e1"], frames["e2"], frames["e3"],
                  frames["e4"], e5=frames["e5"], attr_df=attr_df)
    if paper_out is not None:
        copied = sync_paper_tables(out, paper_out)
        print(f"synced {len(copied)} table/macro files to {paper_out}")
    return frames


def sync_paper_tables(out: Path, paper_out: Path) -> list[str]:
    """Copy the paper's generated tables + macros into the LaTeX project."""
    import shutil

    paper_out = Path(paper_out)
    paper_out.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in PAPER_FILES:
        src = Path(out) / name
        if not src.exists():
            print(f"  ! {name} not produced by this run -- skipped", file=sys.stderr)
            continue
        shutil.copyfile(src, paper_out / name)
        copied.append(name)
    return copied


# --------------------------------------------------------------------------- #
def run(quick: bool = False, out: Path = DEF_OUT, figdir: Path = DEF_FIG,
        translucent: bool = True, seeds: "list[int] | None" = None,
        paper_out: "Path | None" = None) -> dict:
    check_environment(quick)
    out = Path(out)
    figdir = Path(figdir)
    out.mkdir(parents=True, exist_ok=True)
    if seeds is None:
        seeds = [0] if quick else [0, 1, 2]

    # checkpoint each experiment's CSV as soon as it finishes -- the full run is
    # hours long and a crash in a later experiment must not discard earlier work
    e1 = experiment_separation(quick, seeds)
    e1.to_csv(out / "e1_separation.csv", index=False)
    e2 = experiment_quality(quick, translucent)
    e2.to_csv(out / "e2_quality.csv", index=False)
    e3 = experiment_sweeps(quick)
    e3.to_csv(out / "e3_sweeps.csv", index=False)
    e4 = experiment_taskmining(quick, translucent)
    e4.to_csv(out / "e4_taskmining.csv", index=False)
    e5 = experiment_case_study(quick, translucent, seeds)
    e5.to_csv(out / "e5_case_study.csv", index=False)
    attr_df = _attributes_table(quick)
    _write_tables(out, quick, e1, e2, e3, e4, e5=e5, attr_df=attr_df)
    plots.render_all(e1, e2, e3, figdir, attr_df=attr_df, e5=e5)
    if paper_out is not None:
        copied = sync_paper_tables(out, paper_out)
        print(f"synced {len(copied)} table/macro files to {paper_out}")

    return {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5, "attr": attr_df}


def _console_summary(res: dict) -> None:
    e1, e2 = res["e1"], res["e2"]
    print("\n=== E1 separation & recovery (mean over logs/seeds) ===")
    print(e1.groupby("method")[["n_groups", "ari", "nmi", "purity", "sig_per_variant"]]
          .mean().round(3).to_string())
    print("\n=== E2 model quality (per-family mean over logs) ===")
    e2 = _ensure_f1_cols(e2)
    e2cols = ["n_models", "fitness", "precision", "f1", "generalization", "simplicity"]
    for c in ("translucent_fitness", "translucent_precision", "translucent_f1"):
        if c in e2:
            e2cols.append(c)
    print(e2.groupby("method")[[c for c in e2cols if c in e2]].mean().round(3).to_string())
    print("\n=== E4 task mining ===")
    print(res["e4"][["log", "n_views", "roles", "ari", "purity"]].to_string(index=False))
    if "e5" in res and not res["e5"].empty:
        print("\n=== E5 scenario case study (ARI vs noise, mean over seeds) ===")
        piv = res["e5"].pivot_table(index="method", columns="noise", values="ari",
                                    aggfunc="mean").round(3)
        print(piv.reindex([m for m in plots.QUALITY_ROWS if m in piv.index]).to_string())


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()   # set-iteration order must not vary between runs
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true")
    g.add_argument("--full", action="store_true")
    ap.add_argument("--out", default=str(DEF_OUT))
    ap.add_argument("--figdir", default=str(DEF_FIG))
    ap.add_argument("--seeds", type=int, default=None)
    ap.add_argument("--tables-only", dest="tables_only", action="store_true",
                    help="skip the experiments and rebuild every table and macro "
                         "file from the CSVs already in --out")
    ap.add_argument("--paper-out", dest="paper_out", default=None,
                    help="also copy the generated tables and numbers.tex into "
                         "this directory (the LaTeX project's tables/ folder), "
                         "so the paper cannot hold an older run's numbers")
    ap.add_argument("--no-translucent", dest="no_translucent", action="store_true",
                    help="skip the enabled-set-aware translucent fitness / precision "
                         "(on by default)")
    a = ap.parse_args()
    quick = a.quick and not a.full
    seeds = list(range(a.seeds)) if a.seeds else None
    paper_out = Path(a.paper_out) if a.paper_out else None
    if a.tables_only:
        rebuild_tables(Path(a.out), paper_out, quick=quick)
        print(f"\nrebuilt tables in {a.out} from existing CSVs")
        raise SystemExit(0)
    res = run(quick=quick, out=Path(a.out), figdir=Path(a.figdir),
              translucent=not a.no_translucent, seeds=seeds,
              paper_out=paper_out)
    _console_summary(res)
    print(f"\nwrote CSVs + *.tex to {a.out} and figures to {a.figdir}")
