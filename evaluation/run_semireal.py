"""Semi-real evaluation: hidden context recovered from real logs.

This is the answer to the circularity of the synthetic generators.  There, the
enabled sets are written by hand and therefore encode exactly the relationships
``kappa`` reads.  Here the control flow is a real event log, the hidden context
is a *recorded case attribute*, and the enabled sets come from the markings of a
Petri net -- so the behaviour is not designed around the method.

Pipeline, following the enrichment used in the translucent process-mining
literature (Beyel & van der Aalst, DQT@ICPM 2022 / BPM 2024):

  1. read a real log,
  2. split its cases by a real categorical attribute (the "hidden context"),
  3. mine one Inductive Miner -- infrequent model per group,
  4. enrich each group with *its own* model: replay, recording the tau-closed
     set of enabled transitions at every marking,
  5. merge the enriched groups and **drop the attribute**,
  6. hand the result to kappa and to every baseline, and see who recovers it.

Two controls keep the result honest:

  * ``--control`` enriches every case with one *global* model, so no hidden
     context exists.  kappa should then find few views; if it explodes, that is
     the loop-unrolling limitation showing up on real control flow.
  * the per-group models are compared before the experiment runs.  If the
     attribute does not gate behaviour the models coincide, there is nothing to
     recover, and the experiment would be vacuous in the opposite direction.

Input logs must be the **original** public event logs, not the already-translucent
CSVs from the BPM 2024 artefact.  Those CSVs are filtered to the traces fitting
one global model, which collapses the variant space (road traffic 231 -> 35
classical variants, hospital billing 1020 -> 54) and, as a side effect, makes
every case attribute a strict function of the executed sequence.  On the filtered
data no classical variant occurs in more than one group, so control-flow
baselines recover the attribute on their own and the experiment cannot show what
availability adds -- however high the ARI looks.  On the original logs the same
attributes have roughly 99% cross-group variant overlap.  ``run_one`` reports
that overlap and warns when it is zero.

Usage::

    venv/Scripts/python evaluation/run_semireal.py --list
    venv/Scripts/python evaluation/run_semireal.py \
        --source <path to TranslucentActivityRelationships/evaluation>
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import pandas as pd

from evaluation import methods as M
from evaluation.metrics_eval import enabled_incoherence, n_groups, recovery
from tpv.log.enrich import enrich_from_model, split_and_enrich, variants_of
from tpv.log.types import TranslucentLog
from tpv.views.views import induce_views

ROOT = Path(__file__).resolve().parent
DEF_OUT = ROOT / "results"
DEF_SOURCE = Path(
    r"C:/Users/beyel/Documents/Code/TranslucentActivityRelationships/evaluation"
)

#: log -> (relative csv, hidden-context attribute, values to keep or None for all)
#:
#: Sepsis is deliberately absent: the fitting filter leaves 20 cases (BPM 2024,
#: Table 2), which cannot carry a recovery experiment.
#
# IMPORTANT -- read before adding a log here.  The ``04/*.csv`` files from the
# BPM 2024 artefact have already been filtered to the traces fitting one global
# model, which collapses the variant space (road traffic 231 -> 35 classical
# variants, hospital billing 1020 -> 54).  That collapse destroys exactly the
# property this experiment needs: on the filtered logs *no* case attribute has a
# single classical variant occurring in more than one group, so the executed
# activities alone determine the group and nothing is left for availability to
# explain.  On the original logs the same attributes have ~99% overlap.  Use the
# originals.
SEMIREAL_LOGS = {
    "hospital_billing": dict(
        xes="Hospital Billing - Event Log.xes",
        attribute="speciality",
        top_groups=4,
        note="23 specialities in the original log; overlap 99.1%",
    ),
    "road_traffic": dict(
        xes="Road_Traffic_Fine_Management_Process.xes",
        attribute="vehicleClass",
        top_groups=3,
        note="vehicle class; overlap 99.5% in the original log",
    ),
    # screened with evaluation/scan_logs.py: four balanced groups (largest 51%),
    # directly-follows Jaccard 0.57-0.68 between them, and 94% of cases in
    # classical variants shared across groups -- the profile this experiment
    # needs, on a much larger log than the other two
    "bpi2019": dict(
        xes="BPI_Challenge_2019.xes",
        attribute="case:Spend area text",
        top_groups=4,
        note="purchasing; spend area gates the flow, 94% cross-group overlap",
    ),
    # kept for reference: the filtered variants, which do NOT work
    "hospital_billing_filtered": dict(
        csv="hospital_billing/04/54.csv",
        attribute="speciality",
        keep=["C", "A", "K"],
        note="FILTERED artefact -- 0% overlap, cannot isolate availability",
    ),
}

IMF_NOISE = 0.4     # the threshold used to build these logs in BPM 2024


# --------------------------------------------------------------------------- #
def load_xes(path: Path, attribute: str, top_groups: int = 4):
    """Read an *original* (unfiltered) XES log as a classical log + attribute.

    Keeps the ``top_groups`` most frequent attribute values, which is what makes
    the groups big enough to mine a model per group.
    """
    import pm4py

    d = pm4py.read_xes(str(path), return_legacy_log_object=False)
    d = d.dropna(subset=["concept:name", "case:concept:name"])
    d = d.sort_values(["case:concept:name", "time:timestamp"], kind="stable")
    # Take the attribute per *case* from whichever events carry it.  Dropping
    # events whose attribute is NaN would truncate every trace to the events
    # that happen to record it -- in the hospital-billing log that collapses
    # each case to its first event and the whole experiment becomes vacuous.
    attr = (d.groupby("case:concept:name")[attribute]
            .apply(lambda s: s.dropna().iloc[0] if s.notna().any() else None)
            .dropna())
    keep = list(attr.value_counts().head(top_groups).index)
    attr = attr[attr.isin(keep)]
    d = d[d["case:concept:name"].isin(attr.index)]
    cases = (d.groupby("case:concept:name")["concept:name"]
             .apply(lambda s: tuple(s)).to_dict())
    groups = {cid: str(v) for cid, v in attr.items() if cid in cases}
    return cases, groups


def load_classical(csv: Path, attribute: str, keep=None):
    """Read the translucent CSV as a *classical* log plus the chosen attribute.

    Returns ``(cases, groups)`` where ``cases`` maps case id -> activity
    sequence (ordered by timestamp) and ``groups`` maps case id -> attribute
    value.  The recorded ``enabled_activities`` column is deliberately ignored:
    we re-derive availability per group, which is the point of the experiment.
    """
    d = pd.read_csv(csv, low_memory=False)
    d = d.dropna(subset=["concept:name", "case:concept:name"])
    d["time:timestamp"] = pd.to_datetime(d["time:timestamp"], errors="coerce",
                                         utc=True, format="mixed")
    d = d.sort_values(["case:concept:name", "time:timestamp"], kind="stable")

    attr = d.groupby("case:concept:name")[attribute].first()
    if keep is not None:
        attr = attr[attr.isin(keep)]
    attr = attr.dropna()

    d = d[d["case:concept:name"].isin(attr.index)]
    cases = (d.groupby("case:concept:name")["concept:name"]
             .apply(lambda s: tuple(s)).to_dict())
    groups = {cid: str(v) for cid, v in attr.items() if cid in cases}
    return cases, groups


def mine(variants, noise: float = IMF_NOISE):
    """Mine an accepting Petri net from classical variants with IMf."""
    import pm4py
    from pm4py.objects.log.obj import Event, EventLog, Trace

    el = EventLog()
    for seq, case_ids in variants.items():
        for cid in case_ids:
            tr = Trace()
            tr.attributes["concept:name"] = str(cid)
            for act in seq:
                e = Event()
                e["concept:name"] = act
                tr.append(e)
            el.append(tr)
    return pm4py.discover_petri_net_inductive(el, noise_threshold=noise)


def footprint(variants) -> set:
    """Directly-follows pairs of a group -- a cheap proxy for 'these differ'."""
    return {(a, b) for seq in variants for a, b in zip(seq, seq[1:])}


# --------------------------------------------------------------------------- #
def run_one(name: str, spec: dict, source: Path, xes_dir: Path) -> dict:
    if "xes" in spec:
        path = xes_dir / spec["xes"]
        if not path.exists():
            return {"log": name, "error": f"missing {path}"}
        print(f"\n=== {name} ({spec['attribute']}, ORIGINAL log) ===", flush=True)
        cases, groups = load_xes(path, spec["attribute"], spec.get("top_groups", 4))
    else:
        path = source / spec["csv"]
        if not path.exists():
            return {"log": name, "error": f"missing {path}"}
        print(f"\n=== {name} ({spec['attribute']}, FILTERED artefact) ===", flush=True)
        cases, groups = load_classical(path, spec["attribute"], spec.get("keep"))
    labels = sorted(set(groups.values()))
    print(f"  {len(cases):,} cases, {len(labels)} groups: "
          f"{ {g: sum(1 for v in groups.values() if v == g) for g in labels} }")

    by_group = {}
    for g in labels:
        by_group[g] = variants_of({c: s for c, s in cases.items()
                                   if groups[c] == g})

    # -- guard 1: do the groups actually behave differently? -----------------
    fps = {g: footprint(v) for g, v in by_group.items()}
    pairs = [(a, b) for i, a in enumerate(labels) for b in labels[i + 1:]]
    jac = {f"{a}|{b}": len(fps[a] & fps[b]) / max(1, len(fps[a] | fps[b]))
           for a, b in pairs}
    print(f"  directly-follows Jaccard between groups: "
          f"{ {k: round(v, 3) for k, v in jac.items()} }")

    # -- guard 2: is the executed behaviour even ambiguous? ------------------
    #
    # This is the decisive one, and it is easy to miss.  The paper's claim is
    # that the *same* executed sequence can belong to different views, so that
    # availability is the only thing that separates them.  If no classical
    # variant occurs in more than one group, the executed activities already
    # determine the group, variant grouping recovers it too, and the experiment
    # says nothing about what enabled activities add -- however high the ARI.
    var_groups: Dict[Tuple[str, ...], set] = {}
    for cid, seq in cases.items():
        var_groups.setdefault(seq, set()).add(groups[cid])
    shared = {v for v, gs in var_groups.items() if len(gs) > 1}
    shared_cases = sum(1 for cid, seq in cases.items() if seq in shared)
    overlap = shared_cases / max(1, len(cases))
    print(f"  classical variants: {len(var_groups)}; occurring in >1 group: "
          f"{len(shared)} ({overlap:.2%} of cases)")
    if overlap == 0.0:
        print("  ! WARNING: no classical variant is shared between groups, so the "
              "executed\n  ! activities alone determine the group.  A high ARI here "
              "does NOT show that\n  ! enabled activities contribute anything -- "
              "compare against classical_variants.")

    # -- the experiment ------------------------------------------------------
    models = {g: mine(v) for g, v in by_group.items()}
    log, gt, reports = split_and_enrich(
        by_group, discover=lambda v, _g=iter(labels): models[next(_g)],
        name=f"{name}-semireal")
    for r in reports:
        print(f"  {r}")

    rows = []
    k = len(labels)
    groupings = {
        "global": M.group_global(log),
        "kappa": M.group_kappa(log),
        "kappa_supported": M.group_kappa_supported(log),
        "kappa_acts": M.group_kappa_acts(log),
        "classical_variants": M.group_classical_variants(log),
        "translucent_variants": M.group_translucent_variants(log),
    }
    for cname in ("cf_kmeans", "cf_ward", "ctx_kmeans", "enabled", "trace2vec"):
        for suffix, kk in (("@k", k), ("@auto", None)):
            g = _cluster(cname, log, kk)
            if g is not None:
                groupings[f"{cname}{suffix}"] = g

    for method, g in groupings.items():
        r = recovery(gt, M.to_case_labels(log, g))
        inc = enabled_incoherence(log, g)
        rows.append({
            "log": name, "attribute": spec["attribute"], "method": method,
            "k": k, "n_groups": n_groups(g),
            "ari": round(r.get("ari", float("nan")), 4),
            "nmi": round(r.get("nmi", float("nan")), 4),
            "purity": round(r.get("purity", float("nan")), 4),
            "sig_per_variant": round(inc["mean_sig_per_variant"], 4),
            "n_cases": log.n_cases,
            "retention": round(sum(x.n_cases_kept for x in reports)
                               / max(1, sum(x.n_cases_in for x in reports)), 4),
            "cross_group_variant_overlap": round(overlap, 4),
            "min_group_jaccard": round(min(jac.values()), 4) if jac else float("nan"),
        })

    # -- control: one global model, so there is no hidden context ------------
    all_variants = variants_of(cases)
    gnet, gim, gfm = mine(all_variants)
    ctrl_log, ctrl_report = enrich_from_model(all_variants, gnet, gim, gfm,
                                              group="control")
    ctrl_views = len(induce_views(ctrl_log)) if ctrl_log.n_cases else 0
    print(f"  control (one global model, no hidden context): {ctrl_report}; "
          f"kappa finds {ctrl_views} views")
    rows.append({
        "log": name, "attribute": "(control: single global model)",
        "method": "kappa", "k": 1, "n_groups": ctrl_views,
        "ari": float("nan"), "nmi": float("nan"), "purity": float("nan"),
        "sig_per_variant": float("nan"), "n_cases": ctrl_log.n_cases,
        "retention": round(ctrl_report.retention, 4),
    })
    return {"rows": rows, "jaccard": jac,
            "reports": [str(r) for r in reports]}


def _cluster(name, log, k):
    if name == "cf_kmeans":
        return M.group_control_flow_clustering(log, k, "kmeans")
    if name == "cf_ward":
        return M.group_control_flow_clustering(log, k, "ward")
    if name == "ctx_kmeans":
        return M.group_context_aware_clustering(log, k, "kmeans")
    if name == "enabled":
        return M.group_enabled_clustering(log, k, "kmeans")
    if name == "trace2vec":
        return M.group_trace2vec_clustering(log, k)
    raise ValueError(name)


#: paper-facing row order and labels for the semi-real table.  Every computed
#: grouping is shown: the clustering baselines as one row each, with the GT and
#: auto runs paired in a single cell, so the full set costs 9 rows instead of 14.
_SR_SINGLE = ["global", "kappa", "kappa_supported", "kappa_acts",
              "classical_variants", "translucent_variants"]
_SR_PAIRED = ["cf_kmeans", "cf_ward", "ctx_kmeans", "enabled", "trace2vec"]
_SR_LABEL = {
    "global": "global", "kappa": r"$\kappa$ (ours)",
    "kappa_supported": r"$\kappa$ + support (ours)",
    "kappa_acts": r"$\kappa_{\mathit{av}}$ (ours)",
    "classical_variants": "variant discovery",
    "translucent_variants": "translucent-variant grouping",
    "cf_kmeans": r"CF-TC $k$-means", "cf_ward": "CF-TC Ward",
    "ctx_kmeans": "CTX-TC", "enabled": "EN-TC", "trace2vec": "D2V-TC",
    "cf_kmeans@k": r"CF-TC $k$-means (GT)", "cf_kmeans@auto": r"CF-TC $k$-means (auto)",
    "cf_ward@k": r"CF-TC Ward (GT)", "cf_ward@auto": r"CF-TC Ward (auto)",
    "ctx_kmeans@k": "CTX-TC (GT)", "ctx_kmeans@auto": "CTX-TC (auto)",
    "enabled@k": "EN-TC (GT)", "enabled@auto": "EN-TC (auto)",
    "trace2vec@k": "D2V-TC (GT)", "trace2vec@auto": "D2V-TC (auto)",
}
_SR_LOG_LABEL = {"hospital_billing": "hospital billing",
                 "road_traffic": "road traffic"}


def _semireal_table(df: pd.DataFrame) -> str:
    """Rows = groupings, columns = (ARI, #groups) per log.

    Clustering baselines pair their GT and auto runs as ``GT / auto`` in one
    cell.  The best ARI per log is bolded wherever it occurs, paired or not.
    """
    real = df[~df["attribute"].str.startswith("(control")]
    logs = [l for l in ("hospital_billing", "road_traffic")
            if l in set(real["log"])]
    tab = {lg: real[real.log == lg].set_index("method") for lg in logs}
    best = {lg: round(float(pd.to_numeric(tab[lg]["ari"], errors="coerce").max()), 3)
            for lg in logs}

    def one(lg, m, c):
        s = tab[lg]
        if m not in s.index or pd.isna(s.loc[m, c]):
            return "--"
        v = float(s.loc[m, c])
        if c == "n_groups":
            return f"{int(round(v))}"
        txt = f"{v:.3f}"
        return rf"\textbf{{{txt}}}" if round(v, 3) == best[lg] else txt

    n = len(logs)
    lines = [r"\begin{tabular}{l" + "rr" * n + "}", r"\toprule"]
    lines.append(" & " + " & ".join(
        rf"\multicolumn{{2}}{{c}}{{{_SR_LOG_LABEL.get(lg, lg)}}}" for lg in logs) + r" \\")
    lines.append("".join(rf"\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(n)))
    lines.append(" & " + " & ".join("ARI & grp" for _ in logs) + r" \\")
    lines.append(r"\midrule")
    methods = set(real["method"])
    for m in _SR_SINGLE:
        if m in methods:
            cells = [one(lg, m, c) for lg in logs for c in ("ari", "n_groups")]
            lines.append(f"{_SR_LABEL[m]} & " + " & ".join(cells) + r" \\")
    lines.append(r"\midrule")
    for m in _SR_PAIRED:
        if f"{m}@k" not in methods and f"{m}@auto" not in methods:
            continue
        cells = [f"{one(lg, m + '@k', c)} / {one(lg, m + '@auto', c)}"
                 for lg in logs for c in ("ari", "n_groups")]
        lines.append(f"{_SR_LABEL[m]} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(lines)


def _semireal_macros(df: pd.DataFrame) -> str:
    m: "dict[str, str]" = {}
    real = df[~df["attribute"].str.startswith("(control")]
    ctrl = df[df["attribute"].str.startswith("(control")].set_index("log")
    short = {"hospital_billing": "HB", "road_traffic": "RT"}
    for lg, tag in short.items():
        s = real[real.log == lg]
        if s.empty:
            continue
        si = s.set_index("method")
        put = lambda k, v, f="%.3f": m.__setitem__(f"sr{tag}{k}", f % float(v))
        # LaTeX thin-space thousands separator, so 45875 prints as 45,875
        m[f"sr{tag}Cases"] = f"{int(si['n_cases'].iloc[0]):,}".replace(",", r"\,")
        put("K", si["k"].iloc[0], "%d")
        put("Overlap", si["cross_group_variant_overlap"].iloc[0] * 100, "%.1f")
        put("Retention", si["retention"].iloc[0] * 100, "%.1f")
        for meth, key in (("kappa", "Kap"), ("kappa_supported", "Sup"),
                          ("kappa_acts", "Av"), ("classical_variants", "Var"),
                          ("translucent_variants", "TVar")):
            if meth in si.index:
                put(key + "ARI", si.loc[meth, "ari"])
                put(key + "NMI", si.loc[meth, "nmi"])
                put(key + "Groups", si.loc[meth, "n_groups"], "%d")
                put(key + "Sig", si.loc[meth, "sig_per_variant"], "%.2f")
                # kappa's views are pure but far too many: report both, so the
                # low ARI is read as over-segmentation rather than mis-grouping
                put(key + "Purity", si.loc[meth, "purity"], "%.2f")
                put(key + "PerGroup", si.loc[meth, "n_groups"] / max(1, si.loc[meth, "k"]), "%.0f")
        # best competing baseline (not kappa, not the two variant groupings)
        # a *competing* baseline: none of our own groupings, and not the two
        # variant groupings or the single global model
        ours = ("kappa", "kappa_supported", "kappa_acts",
                "classical_variants", "translucent_variants", "global")
        base = si.drop(index=[i for i in ours if i in si.index])
        if not base.empty:
            b = base["ari"].idxmax()
            m[f"sr{tag}BestBase"] = _SR_LABEL.get(b, b)
            put("BestBaseARI", base.loc[b, "ari"])
        if lg in ctrl.index:
            put("CtrlViews", ctrl.loc[lg, "n_groups"], "%d")
    head = ("% AUTOGENERATED by evaluation/run_semireal.py -- do not edit.\n"
            "% Regenerate with: venv/Scripts/python evaluation/run_semireal.py\n")
    return head + "".join(rf"\newcommand{{\{k}}}{{{v}}}" + "\n"
                          for k, v in sorted(m.items()))


def _write_outputs(df: pd.DataFrame, out: Path, paper_out) -> None:
    (out / "semireal_table.tex").write_text(_semireal_table(df), encoding="utf-8")
    (out / "numbers_semireal.tex").write_text(_semireal_macros(df), encoding="utf-8")
    if paper_out:
        import shutil
        po = Path(paper_out); po.mkdir(parents=True, exist_ok=True)
        for n in ("semireal_table.tex", "numbers_semireal.tex"):
            shutil.copyfile(out / n, po / n)
        print(f"synced 2 files to {po}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEF_SOURCE))
    ap.add_argument("--xes-dir", dest="xes_dir",
                    default=r"C:/Users/beyel/Documents/Code/cabumm/data",
                    help="directory holding the original (unfiltered) XES logs")
    ap.add_argument("--out", default=str(DEF_OUT))
    ap.add_argument("--only", default=None, help="run a single log by name")
    ap.add_argument("--exclude", nargs="*", default=[], help="skip these logs")
    ap.add_argument("--paper-out", dest="paper_out", default=None,
                    help="also copy the generated table and macros into the "
                         "LaTeX project's tables/ directory")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--tables-only", dest="tables_only", action="store_true",
                    help="rebuild the table and macros from s1_semireal.csv without rerunning")
    a = ap.parse_args()

    if a.list:
        for name, spec in SEMIREAL_LOGS.items():
            print(f"{name:20s} attribute={spec['attribute']:12s} {spec['note']}")
        return 0

    source, out = Path(a.source), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.tables_only:
        df = pd.read_csv(out / "s1_semireal.csv")
        _write_outputs(df, out, a.paper_out)
        return 0
    rows = []
    for name, spec in SEMIREAL_LOGS.items():
        if a.only and name != a.only:
            continue
        if name in a.exclude:
            continue
        if not a.only and name.endswith("_filtered"):
            continue        # reference only; see the note on SEMIREAL_LOGS
        res = run_one(name, spec, source, Path(a.xes_dir))
        if "error" in res:
            print(f"  ! {res['error']}", file=sys.stderr)
            continue
        rows.extend(res["rows"])
    if not rows:
        print("nothing ran", file=sys.stderr)
        return 1
    df = pd.DataFrame(rows)
    df.to_csv(out / "s1_semireal.csv", index=False)
    _write_outputs(df, out, a.paper_out)
    print(f"\nwrote {out / 's1_semireal.csv'}")
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()   # set-iteration order must not vary between runs
    raise SystemExit(main())
