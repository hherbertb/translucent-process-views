"""Data-free experiments backing Section 4's claims about kappa itself.

These are deliberately separate from ``run_evaluation.py``: none of them
discovers a model or computes an alignment, so they run in minutes rather than
hours and can be re-run without repeating the expensive harness.

  P1  cost          -- runtime of kappa vs. the clustering baselines, by log size
  P2  determinism   -- kappa's variance across seeds is exactly zero; the
                       clustering baselines' is not
  P3  loop penalty  -- how fast kappa's view count grows when it unrolls a loop
  P4  tie-break     -- whether Definition 4.8's leftmost-longest window is
                       load-bearing, against two alternative decompositions

Usage::

    venv/Scripts/python evaluation/run_properties.py
    venv/Scripts/python evaluation/run_properties.py --paper-out <overleaf>/tables
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import pandas as pd

from evaluation import methods as M
from evaluation.metrics_eval import recovery
from tpv.log.demo import loop_process_log
from tpv.log.synth import enterprise_log, k_view_log, partial_parallel_log, running_example_log
from tpv.views.abstraction import DECOMPOSITIONS, kappa
from tpv.views.views import induce_views

ROOT = Path(__file__).resolve().parent
DEF_OUT = ROOT / "results"

_SIZES = (250, 500, 1000, 2000, 4000)
_GENERATORS = {
    "running_example": lambda n, s: running_example_log(n, seed=s),
    "k_view_k4": lambda n, s: k_view_log(4, max(2, n // 4), seed=s),
    "parallel_choices": lambda n, s: partial_parallel_log(n, seed=s),
    "enterprise": lambda n, s: enterprise_log(n, 5, seed=s),
}


# --------------------------------------------------------------------------- #
# P1 -- cost
# --------------------------------------------------------------------------- #
def experiment_cost(sizes=_SIZES, repeats: int = 3) -> pd.DataFrame:
    """Wall-clock time to produce a partition, kappa vs. the baselines.

    kappa's headline claim is that it needs no distance function, no cluster
    count and no clustering algorithm.  That claim is about machinery, but it
    implies a cost story that the paper never measured.  Baselines are given
    ``k = GT`` so they are timed at their cheapest (no silhouette search).
    """
    rows = []
    for gen_name, gen in _GENERATORS.items():
        for n in sizes:
            log, gt, _ = gen(n, 1)
            k = len(set(gt.values()))
            n_traces = len(log.trace_set())
            methods = {
                "kappa": lambda: M.group_kappa(log),
                "cf_kmeans@k": lambda: M.group_control_flow_clustering(log, k, "kmeans"),
                "cf_ward@k": lambda: M.group_control_flow_clustering(log, k, "ward"),
                "ctx_kmeans@k": lambda: M.group_context_aware_clustering(log, k, "kmeans"),
                "enabled@k": lambda: M.group_enabled_clustering(log, k, "kmeans"),
                "trace2vec@k": lambda: M.group_trace2vec_clustering(log, k),
            }
            for method, fn in methods.items():
                best = None
                for _ in range(repeats):
                    t0 = time.perf_counter()
                    g = fn()
                    dt = time.perf_counter() - t0
                    if g is None:
                        best = None
                        break
                    best = dt if best is None else min(best, dt)
                if best is None:
                    continue
                rows.append({"log": gen_name, "n_cases": log.n_cases,
                             "n_traces": n_traces, "method": method,
                             "seconds": round(best, 4)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# P2 -- determinism
# --------------------------------------------------------------------------- #
def experiment_determinism(seeds=(0, 1, 2, 3, 4)) -> pd.DataFrame:
    """Spread of ARI across seeds, per method.

    kappa is a function of the trace alone, so re-running it cannot move the
    partition: its std is exactly 0.  Every clustering baseline depends on an
    initialisation.  The main harness already runs several seeds but averages
    the spread away, which hides a direct argument for the design.
    """
    rows = []
    for gen_name, gen in _GENERATORS.items():
        for seed in seeds:
            log, gt, attrs = gen(1000, seed)
            gt_cases, k = dict(gt), len(set(gt.values()))
            groupings = {"kappa": M.group_kappa(log)}
            for name, fn in (
                ("cf_kmeans@k", lambda: M.group_control_flow_clustering(log, k, "kmeans")),
                ("cf_ward@k", lambda: M.group_control_flow_clustering(log, k, "ward")),
                ("ctx_kmeans@k", lambda: M.group_context_aware_clustering(log, k, "kmeans")),
                ("enabled@k", lambda: M.group_enabled_clustering(log, k, "kmeans")),
                ("trace2vec@k", lambda: M.group_trace2vec_clustering(log, k)),
            ):
                g = fn()
                if g is not None:
                    groupings[name] = g
            for method, g in groupings.items():
                r = recovery(gt_cases, M.to_case_labels(log, g))
                rows.append({"log": gen_name, "seed": seed, "method": method,
                             "ari": r["ari"], "n_groups": len(set(g.values()))})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# P3 -- loop penalty
# --------------------------------------------------------------------------- #
def experiment_loop_penalty(max_reworks=(0, 1, 2, 3, 4, 5, 6, 8, 10)) -> pd.DataFrame:
    """View count vs. how many times the loop may repeat.

    K has no loop operator (Section 4.1), so repetition is unrolled and each
    distinct repeat count becomes its own view.  The paper reports this with a
    single number in the log table; the growth curve is what makes the scope
    restriction concrete and bounded rather than merely admitted.
    """
    rows = []
    for mr in max_reworks:
        log = loop_process_log(600, seed=13, max_rework=mr)
        lengths = {len(t) for t in log.trace_set()}
        rows.append({
            "max_rework": mr,
            "n_views": len(induce_views(log)),
            "n_translucent_variants": len(log.trace_set()),
            "n_classical_variants": len(log.classical_variants()),
            "distinct_trace_lengths": len(lengths),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# P4 -- tie-break ablation
# --------------------------------------------------------------------------- #
def experiment_tiebreak() -> pd.DataFrame:
    """Do the alternative decompositions induce a different partition?

    Definition 4.8 fixes the leftmost-longest parallel-supported window.  If the
    induced views coincide under a right-to-left and a shortest-window scan, the
    tie-break is not load-bearing and the paper can say so; where they differ,
    the choice needs justifying.
    """
    rows = []
    for gen_name, gen in _GENERATORS.items():
        log, gt, _ = gen(1000, 1)
        gt_cases = dict(gt)
        base = None
        for name in DECOMPOSITIONS:
            ids = {t: kappa(t, name).canonical_str() for t in log.trace_set()}
            cases = {cid: ids[t] for t in log.trace_set() for cid in log.case_ids[t]}
            r = recovery(gt_cases, cases)
            if base is None:
                base = cases
            agree = recovery(base, cases)["ari"]
            rows.append({
                "log": gen_name, "decomposition": name,
                "n_views": len(set(ids.values())),
                "ari_vs_ground_truth": round(r["ari"], 4),
                "ari_vs_definition_4_8": round(agree, 4),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def _macros(cost, det, loop, tie) -> str:
    m: "dict[str, str]" = {}

    # Cost is only comparable within one log (the logs differ by an order of
    # magnitude in how many *distinct translucent traces* they contain, which is
    # what kappa actually iterates over).  Aggregating across logs produces a
    # meaningless "speed-up", so report the scaling instead: seconds per 1000
    # cases as the log grows.  Flat = linear; rising = superlinear.
    if not cost.empty:
        c = cost.copy()
        c["per_kilo"] = c.seconds / (c.n_cases / 1000.0)
        hard = c[c.log == "enterprise"]           # most distinct traces
        m["costMaxCases"] = f"{int(cost.n_cases.max())}"
        if not hard.empty:
            piv = hard.pivot_table(index="n_cases", columns="method",
                                   values="per_kilo")
            lo, hi = piv.index.min(), piv.index.max()
            for method, key in (("kappa", "Kappa"), ("cf_ward@k", "Ward"),
                                ("cf_kmeans@k", "KMeans"),
                                ("trace2vec@k", "DtoV")):
                if method in piv.columns:
                    m[f"costPerKilo{key}Small"] = f"{piv.loc[lo, method]:.2f}"
                    m[f"costPerKilo{key}Large"] = f"{piv.loc[hi, method]:.2f}"
            if "kappa" in piv.columns and "cf_ward@k" in piv.columns:
                m["costWardGrowth"] = (
                    f"{piv.loc[hi, 'cf_ward@k'] / piv.loc[lo, 'cf_ward@k']:.1f}")
                m["costKappaGrowth"] = (
                    f"{piv.loc[hi, 'kappa'] / piv.loc[lo, 'kappa']:.1f}")
        # the log where kappa is cheapest relative to the baselines
        big = c[c.n_cases == c.n_cases.max()]
        cheap = big[big.log == "running_example"]
        if not cheap.empty and "kappa" in set(cheap.method):
            kv = cheap[cheap.method == "kappa"]["seconds"].iloc[0]
            m["costKappaFewTraces"] = f"{kv:.3f}"

    if not det.empty:
        sd = det.groupby("method")["ari"].std().fillna(0.0)
        m["detKappaStd"] = f"{sd.get('kappa', 0.0):.3f}"
        others = sd.drop(index="kappa", errors="ignore")
        if not others.empty:
            m["detBaselineStdMax"] = f"{others.max():.3f}"
            m["detBaselineStdMedian"] = f"{others.median():.3f}"
        m["detSeeds"] = f"{det.seed.nunique()}"

    if not loop.empty:
        m["loopViewsMin"] = f"{int(loop.n_views.min())}"
        m["loopViewsMax"] = f"{int(loop.n_views.max())}"
        m["loopMaxRework"] = f"{int(loop.max_rework.max())}"
        # The generator's rework count is geometric and effectively saturates,
        # so the tail (where raising max_rework no longer produces longer
        # traces) would flatten an average slope and understate the growth.
        # Measure only where the view count is still moving.
        grow = loop[loop.n_views < loop.n_views.max()]
        if len(grow) > 1:
            slope = ((grow.n_views.iloc[-1] - grow.n_views.iloc[0])
                     / (grow.max_rework.iloc[-1] - grow.max_rework.iloc[0]))
            m["loopSlope"] = f"{slope:.2f}"
            m["loopSaturatesAt"] = f"{int(loop[loop.n_views == loop.n_views.max()].max_rework.min())}"
        # kappa produces exactly one view per distinct trace length here, which
        # is the whole content of the "unrolls loops" limitation
        m["loopViewsEqualLengths"] = (
            "yes" if (loop.n_views == loop.distinct_trace_lengths).all() else "no")

    if not tie.empty:
        alt = tie[tie.decomposition != "leftmost_longest"]
        m["tieAltCount"] = f"{tie.decomposition.nunique() - 1}"
        m["tieMinAgreement"] = f"{alt['ari_vs_definition_4_8'].min():.3f}"
        m["tieAllIdentical"] = ("yes" if (alt["ari_vs_definition_4_8"] >= 0.9999).all()
                                else "no")

    head = ("% AUTOGENERATED by evaluation/run_properties.py -- do not edit.\n"
            "% Regenerate with: venv/Scripts/python evaluation/run_properties.py\n")
    return head + "".join(rf"\newcommand{{\{k}}}{{{v}}}" + "\n"
                          for k, v in sorted(m.items()))


def run(out: Path = DEF_OUT, paper_out: "Path | None" = None) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    print("P1 cost ...", flush=True)
    cost = experiment_cost()
    cost.to_csv(out / "p1_cost.csv", index=False)
    print("P2 determinism ...", flush=True)
    det = experiment_determinism()
    det.to_csv(out / "p2_determinism.csv", index=False)
    print("P3 loop penalty ...", flush=True)
    loop = experiment_loop_penalty()
    loop.to_csv(out / "p3_loop.csv", index=False)
    print("P4 tie-break ...", flush=True)
    tie = experiment_tiebreak()
    tie.to_csv(out / "p4_tiebreak.csv", index=False)

    (out / "numbers_properties.tex").write_text(
        _macros(cost, det, loop, tie), encoding="utf-8")
    (out / "loop_penalty_table.tex").write_text(
        loop.rename(columns={
            "max_rework": "max.\\ rework", "n_views": "$\\kappa$ views",
            "n_translucent_variants": "tr.\\ var.",
            "n_classical_variants": "cl.\\ var.",
            "distinct_trace_lengths": "distinct lengths",
        }).to_latex(index=False, escape=False, column_format="rrrrr"),
        encoding="utf-8")

    if paper_out is not None:
        import shutil
        paper_out = Path(paper_out)
        paper_out.mkdir(parents=True, exist_ok=True)
        for name in ("numbers_properties.tex", "loop_penalty_table.tex"):
            shutil.copyfile(out / name, paper_out / name)
        print(f"synced 2 files to {paper_out}")

    return {"cost": cost, "determinism": det, "loop": loop, "tiebreak": tie}


def _summary(res: dict) -> None:
    print("\n=== P1 cost (seconds, largest size) ===")
    c = res["cost"]
    big = c[c.n_cases == c.n_cases.max()]
    print(big.groupby("method")["seconds"].mean().round(3).to_string())
    print("\n=== P2 ARI std across seeds ===")
    print(res["determinism"].groupby("method")["ari"].std().fillna(0.0)
          .round(4).to_string())
    print("\n=== P3 loop penalty ===")
    print(res["loop"].to_string(index=False))
    print("\n=== P4 tie-break (ARI vs Definition 4.8's partition) ===")
    print(res["tiebreak"].to_string(index=False))


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()   # set-iteration order must not vary between runs
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEF_OUT))
    ap.add_argument("--paper-out", dest="paper_out", default=None)
    a = ap.parse_args()
    _summary(run(Path(a.out), Path(a.paper_out) if a.paper_out else None))
