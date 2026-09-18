"""Figures for the evaluation (matplotlib only, flat academic style).

Every ``fig_*`` takes the relevant experiment DataFrame plus a target directory
and writes ``<name>.pdf`` and ``<name>.png``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "figure.dpi": 120,
})

BLUE = "#2563EB"
GREY = "#98A2B3"
GREEN = "#067647"
ORANGE = "#F58518"
PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#9D755D"]

# canonical method order / short labels
METHOD_ORDER = [
    "global", "kappa",
    "cf_kmeans@auto", "cf_ward@auto", "ctx_kmeans@auto", "trace2vec@auto",
    "enabled@auto", "attr_clean@auto", "attr_noisy@auto", "attr_all@auto",
    "cf_kmeans@k", "cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k",
    "attr_clean@k", "attr_noisy@k", "attr_all@k",
    "classical_variants", "translucent_variants",
]
LABEL = {
    "global": "global",
    "kappa": r"$\kappa$ (ours)",
    "kappa_identifier": r"$\kappa$ identifier",
    "classical_variants": "classical\nvariants",
    "translucent_variants": "translucent\nvariants",
    "cf_kmeans@auto": "cf k-means\n(k=auto)",
    "cf_ward@auto": "cf Ward\n(k=auto)",
    "ctx_kmeans@auto": "ctx k-means\n(k=auto)",
    "trace2vec@auto": "trace2vec\n(k=auto)",
    "enabled@auto": "enabled-only\n(k=auto)",
    "attr_clean@auto": "attr clean\n(k=auto)",
    "attr_noisy@auto": "attr noisy\n(k=auto)",
    "attr_all@auto": "attr all\n(k=auto)",
    "cf_kmeans@k": "cf k-means\n(k=GT)",
    "cf_ward@k": "cf Ward\n(k=GT)",
    "ctx_kmeans@k": "ctx k-means\n(k=GT)",
    "trace2vec@k": "trace2vec\n(k=GT)",
    "enabled@k": "enabled-only\n(k=GT)",
    "attr_clean@k": "attr clean\n(k=GT)",
    "attr_noisy@k": "attr noisy\n(k=GT)",
    "attr_all@k": "attr all\n(k=GT)",
}

# canonical row order for the model-quality table / heatmaps: every grouping the
# experiments score, kappa_identifier included
QUALITY_ROWS = ["global", "kappa", "kappa_identifier"] + [
    m for m in METHOD_ORDER if m not in ("global", "kappa")
]


def _save(fig, figdir: Path, name: str) -> None:
    figdir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(figdir / f"{name}.{ext}", bbox_inches="tight")
    plt.close(fig)


def _order(methods: Sequence[str]) -> list:
    present = set(methods)
    return [m for m in METHOD_ORDER if m in present]


# --------------------------------------------------------------------------- #
# silhouette-chosen k for the clustering baselines: the only variants that can
# actually under- or over-separate (the k=GT variants are pinned to k by design
# and belong in the recovery figure instead)
_SEPARATION_METHODS = [
    "global", "kappa",
    "cf_ward@auto", "ctx_kmeans@auto", "trace2vec@auto", "enabled@auto",
    "attr_clean@auto", "attr_noisy@auto",
    "classical_variants", "translucent_variants",
]


def fig_separation(e1: pd.DataFrame, figdir: Path) -> None:
    d = e1.copy()
    present = set(d["method"])
    methods = [m for m in _SEPARATION_METHODS if m in present]
    kk = d.groupby(["log", "seed"])["k"].first().dropna().values
    cats = ["hidden $k$"] + methods
    fig, ax = plt.subplots(figsize=(8.8, 2.8))
    data = [kk] + [d.loc[d.method == m, "n_groups"].values for m in methods]
    bp = ax.boxplot(data, positions=range(len(cats)), widths=0.62, patch_artist=True,
                    showfliers=False, medianprops=dict(color="black"))
    for i, patch in enumerate(bp["boxes"]):
        cat = cats[i]
        patch.set_facecolor(BLUE if i == 0 else GREEN if cat == "kappa" else "#dfe3ea")
        patch.set_edgecolor("#667085")
    ax.axhline(1.0, color="#c0c4cc", lw=0.6, zorder=0)
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(["hidden $k$"] + [LABEL.get(m, m) for m in methods],
                       rotation=20, ha="right", fontsize=7.5)
    ax.set_yscale("log")
    ax.set_ylabel("number of groups / models")
    ax.set_title("Separation: groups produced per method (log scale; "
                 "clustering with $k$ by silhouette)", fontsize=9)
    _save(fig, figdir, "fig_separation")


_RECOVERY_METHODS = [
    "kappa", "cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k",
    "attr_clean@k", "attr_noisy@k", "attr_all@k",
    "classical_variants", "translucent_variants",
]


def fig_recovery(e1: pd.DataFrame, figdir: Path) -> None:
    d = e1.dropna(subset=["ari"]).copy()
    present = set(d["method"])
    methods = [m for m in _RECOVERY_METHODS if m in present]
    fig, ax = plt.subplots(figsize=(8.6, 2.7))
    data = [d.loc[d.method == m, "ari"].values for m in methods]
    bp = ax.boxplot(data, positions=range(len(methods)), widths=0.6, patch_artist=True,
                    showfliers=True, medianprops=dict(color="black"),
                    flierprops=dict(marker="o", markersize=2.5, alpha=0.4))
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(GREEN if methods[i] == "kappa" else "#dfe3ea")
        patch.set_edgecolor("#667085")
        vals = data[i]
        if len(vals) and float(vals.max() - vals.min()) < 1e-9:  # degenerate box
            colour = GREEN if methods[i] == "kappa" else "#667085"
            ax.scatter([i], [vals.mean()], marker="s", s=36, color=colour, zorder=6)
    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels([LABEL.get(m, m) for m in methods], rotation=20, ha="right",
                       fontsize=7.5)
    ax.set_ylabel("adjusted Rand index vs. hidden context")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("Recovery of the hidden context ($k=\\mathrm{GT}$ for every "
                 "clustering baseline)", fontsize=9)
    _save(fig, figdir, "fig_recovery")


def fig_enabled_incoherence(e1: pd.DataFrame, figdir: Path) -> None:
    d = e1.dropna(subset=["sig_per_variant"]).copy()
    keep = ["global", "classical_variants", "kappa"]  # translucent_variants trivially = 1
    methods = [m for m in keep if m in set(d.method)]
    means = [d.loc[d.method == m, "sig_per_variant"].mean() for m in methods]
    errs = [d.loc[d.method == m, "sig_per_variant"].std() for m in methods]
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    bars = ax.bar(range(len(methods)), means, yerr=errs, capsize=3,
                  color=[GREEN if m == "kappa" else "#dfe3ea" for m in methods],
                  edgecolor="#667085")
    ax.axhline(1.0, color=BLUE, lw=1, ls="--", label="coherent (= 1)")
    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels([LABEL.get(m, m) for m in methods], fontsize=7.5)
    ax.set_ylabel("distinct enabled-signatures\nper (group, classical variant)")
    ax.set_title("Enabled-activity coherence within groups", fontsize=9)
    ax.legend(frameon=False, fontsize=7.5)
    _save(fig, figdir, "fig_enabled_incoherence")


# (column, short display label) for the eight model-quality metrics
_QUALITY_METRICS = [
    ("fitness", "fitness"), ("precision", "precision"), ("f1", "F1"),
    ("generalization", "general."), ("simplicity", "simplic."),
    ("translucent_fitness", "t-fit."), ("translucent_precision", "t-prec."),
    ("translucent_f1", "t-F1"),
]


def _with_f1(e2: pd.DataFrame) -> pd.DataFrame:
    """Add f1 / translucent_f1 columns if the CSV predates them."""
    from evaluation.metrics_eval import harmonic_f1
    e2 = e2.copy()
    if "f1" not in e2 and {"fitness", "precision"} <= set(e2.columns):
        e2["f1"] = [harmonic_f1(a, b) for a, b in zip(e2.fitness, e2.precision)]
    if "translucent_f1" not in e2 and \
            {"translucent_fitness", "translucent_precision"} <= set(e2.columns):
        e2["translucent_f1"] = [harmonic_f1(a, b) for a, b in
                                zip(e2.translucent_fitness, e2.translucent_precision)]
    return e2


def fig_quality(e2: pd.DataFrame, figdir: Path) -> None:
    """Heatmap: every approach (rows) x the eight model-quality metrics (cols),
    per-family mean over logs. Mean model count folded into the row label."""
    import matplotlib.colors as mcolors

    e2 = _with_f1(e2)
    metrics = [(c, lab) for c, lab in _QUALITY_METRICS if c in e2.columns]
    rows = [m for m in QUALITY_ROWS if m in set(e2.method)]
    g = e2[e2.method.isin(rows)].groupby("method")
    agg = g[[c for c, _ in metrics]].mean().reindex(rows)
    nmods = g["n_models"].mean().reindex(rows)
    agg.index = [f"{LABEL.get(m, m).replace(chr(10), ' ')}  ({nmods[m]:.0f} mdl)"
                 for m in rows]
    agg.columns = [lab for _, lab in metrics]

    fig, ax = plt.subplots(figsize=(7.4, 0.34 * len(rows) + 1.0))
    im = _heatmap(ax, agg, cmap="RdYlGn", norm=mcolors.Normalize(0.4, 1.0),
                  fmt="{:.2f}", title="Model quality per approach "
                  "(per-family mean over logs)", label_fs=7.0, annot_fs=6.5)
    ax.axvline(4.5, color="#33383f", lw=1.0)  # classic | translucent divider
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02).ax.tick_params(labelsize=6)
    fig.tight_layout()
    _save(fig, figdir, "fig_quality")


def fig_compactness(e2: pd.DataFrame, figdir: Path) -> None:
    """Mean models vs. mean precision, one labelled point per method."""
    agg = e2.groupby("method").agg(n_models=("n_models", "mean"),
                                   precision=("precision", "mean"),
                                   simplicity=("simplicity", "mean"))
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    for i, m in enumerate(agg.index):
        colour = GREEN if m == "kappa" else PALETTE[i % len(PALETTE)]
        ax.scatter(max(agg.loc[m, "n_models"], 0.9), agg.loc[m, "precision"],
                   s=70, color=colour, edgecolor="white", linewidth=0.6, zorder=4)
        ax.annotate(LABEL.get(m, m).replace("\n", " "),
                    (max(agg.loc[m, "n_models"], 0.9), agg.loc[m, "precision"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=7)
    ax.set_xscale("log")
    ax.set_xlabel("mean number of models (log scale)")
    ax.set_ylabel("mean frequency-weighted precision")
    ax.set_title("Compactness vs. precision", fontsize=9)
    ax.margins(x=0.25, y=0.15)
    _save(fig, figdir, "fig_compactness")


def fig_noise(e3: pd.DataFrame, figdir: Path) -> None:
    """Two rows: (top) recovery ARI vs. enabled-set noise for kappa vs. the
    control-flow clustering baseline; (bottom) kappa's view count, which explodes
    as the enabled sets are corrupted."""
    d = e3[e3["sweep"] == "noise"].copy()
    _sweep_title = {"running_example": "running example", "k_view_k4": "$k$-view ($k$=4)"}
    logs = sorted(d["log"].unique())
    nc = max(len(logs), 1)
    fig, axes = plt.subplots(2, nc, figsize=(3.3 * nc, 3.2), squeeze=False,
                             sharex="col", gridspec_kw={"height_ratios": [1.5, 1]})
    n_cf = 5  # cf_kmeans, cf_ward, ctx_kmeans, trace2vec, enabled
    for j, lg in enumerate(logs):
        s = d[d.log == lg]
        top, bot = axes[0][j], axes[1][j]
        kap = s[s.method == "kappa"].sort_values("value")
        cm = s[s.method == "clustering_mean"].sort_values("value")
        cb = s[s.method == "clustering_best"].sort_values("value")
        top.plot(kap["value"], kap["ari"], "-o", ms=3, color=GREEN, label=r"$\kappa$")
        if not cm.empty:
            top.plot(cm["value"], cm["ari"], "-s", ms=3, color=ORANGE,
                     label=f"clustering (mean of {n_cf})")
        if not cb.empty:
            top.plot(cb["value"], cb["ari"], "--", lw=0.9, color=ORANGE, alpha=0.7,
                     label="clustering (best)")
        top.set_title(_sweep_title.get(lg, lg), fontsize=8)
        top.set_ylim(-0.05, 1.05)
        bot.plot(kap["value"], kap["n_groups"], "-o", ms=3, color=GREEN)
        bot.axhline(kap["n_groups"].iloc[0], color="#c0c4cc", lw=0.7, ls=":")
        bot.set_yscale("log")
        bot.set_xlabel("enabled-set noise")
    axes[0][0].set_ylabel("ARI vs.\nhidden context", fontsize=8)
    axes[1][0].set_ylabel(r"$\kappa$ views" "\n(log scale)", fontsize=8)
    axes[0][0].legend(frameon=False, fontsize=6.5)
    fig.suptitle("Recovery and view count under enabled-set noise", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.95), h_pad=0.6)
    _save(fig, figdir, "fig_noise")


def fig_attributes(attr_df: pd.DataFrame, figdir: Path) -> None:
    """NMI between each recorded case attribute and the hidden label, split into
    the clean (informative) and noisy (uninformative) sets. Every bar is
    annotated with its value so the near-zero noisy bars stay legible."""
    d = attr_df.copy()
    col = "NMI w/ hidden label" if "NMI w/ hidden label" in d.columns \
        else "NMI w/ hidden $k$"
    d = d.sort_values(["kind", col], ascending=[True, False])
    names = [a.replace(r"\_", "_") for a in d["attribute"]]
    vals = d[col].astype(float).values
    colours = [BLUE if k == "clean" else GREY for k in d["kind"]]
    fig, ax = plt.subplots(figsize=(6.6, 3.2))
    bars = ax.bar(range(len(names)), vals, color=colours, edgecolor="#667085")
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.3f}", (b.get_x() + b.get_width() / 2, max(v, 0) + 0.02),
                    ha="center", fontsize=6.5, color="#475467")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=25, ha="right", fontsize=7.5)
    ax.set_ylabel("NMI with the hidden label")
    ax.set_ylim(0, 1.12)
    ax.set_title("Recorded case attributes: information about the hidden context",
                 fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE),
               plt.Rectangle((0, 0), 1, 1, color=GREY)]
    ax.legend(handles, ["clean (informative)", "noisy (uninformative)"],
              frameon=False, fontsize=7.5, loc="upper right")
    _save(fig, figdir, "fig_attributes")


# the #groups panel mirrors fig_separation (clustering with k by silhouette);
# the ARI panel mirrors fig_recovery (clustering given k = GT)
_PERLOG_GROUPS_METHODS = list(_SEPARATION_METHODS)
_PERLOG_ARI_METHODS = ["kappa"] + list(_RECOVERY_METHODS[1:])


def _perlog_pivot(e1: pd.DataFrame, value: str, methods) -> pd.DataFrame:
    piv = e1.pivot_table(index="method", columns="log", values=value, aggfunc="mean")
    return piv.reindex([m for m in methods if m in piv.index])


def _heatmap(ax, piv: pd.DataFrame, *, norm=None, cmap="viridis", fmt="{:.2f}",
             annot_thresh=None, title="", label_fs=7.0, annot_fs=6.3):
    import matplotlib.colors as mcolors

    data = piv.to_numpy(dtype=float)
    im = ax.imshow(data, aspect="auto", cmap=cmap,
                   norm=norm or mcolors.Normalize(vmin=0.0, vmax=1.0))
    ax.set_xticks(range(piv.shape[1]))
    ax.set_xticklabels(list(piv.columns), rotation=40, ha="right", fontsize=label_fs)
    ax.set_yticks(range(piv.shape[0]))
    ax.set_yticklabels([LABEL.get(m, m).replace("\n", " ") for m in piv.index],
                       fontsize=label_fs + 0.2)
    ax.set_xticks(np.arange(-.5, piv.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-.5, piv.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.6)
    ax.tick_params(which="minor", length=0)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = data[i, j]
            if np.isnan(v):
                ax.text(j, i, "--", ha="center", va="center", fontsize=6, color="#98A2B3")
                continue
            rgba = im.cmap(im.norm(v))
            lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
            ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=annot_fs,
                    color="white" if lum < 0.5 else "#1d2939")
    ax.set_title(title, fontsize=9)
    return im


def fig_perlog(e1: pd.DataFrame, figdir: Path) -> None:
    """Appendix: per-log versions of Fig. separation and Fig. recovery.

    Left panel = number of groups, clustering with ``k`` by silhouette (mirrors
    ``fig_separation``).  Right panel = recovery ARI, clustering given
    ``k = GT`` (mirrors ``fig_recovery``).  The two panels therefore list
    different method rows -- exactly as the two aggregate figures do.
    """
    import matplotlib.colors as mcolors

    grp = _perlog_pivot(e1, "n_groups", _PERLOG_GROUPS_METHODS)
    ari = _perlog_pivot(e1, "ari", _PERLOG_ARI_METHODS)
    ari = ari.drop(columns=[c for c in ari.columns if ari[c].isna().all()],
                   errors="ignore")
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.3),
                             gridspec_kw={"width_ratios": [1.12, 1]})
    gmax = float(np.nanmax(grp.to_numpy(dtype=float)))
    im0 = _heatmap(axes[0], grp, cmap="magma_r",
                   norm=mcolors.LogNorm(vmin=1, vmax=max(gmax, 10)), fmt="{:.0f}",
                   title=r"(a) groups produced, $k$ by silhouette (cf. Fig. 1)")
    fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.02).ax.tick_params(labelsize=6)
    im1 = _heatmap(axes[1], ari, cmap="RdYlGn",
                   norm=mcolors.Normalize(0.0, 1.0), fmt="{:.2f}",
                   title=r"(b) recovery ARI, $k=\mathrm{GT}$ (cf. Fig. 2)")
    fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.02).ax.tick_params(labelsize=6)
    fig.tight_layout()
    _save(fig, figdir, "fig_perlog")


def fig_quality_perlog(e2: pd.DataFrame, figdir: Path) -> None:
    """Appendix: the eight model-quality metrics of ``fig_quality`` broken out by
    log -- a 2x4 grid of method x log heatmaps."""
    import matplotlib.colors as mcolors

    e2 = _with_f1(e2)
    # fitness and translucent precision are ~constant across approaches -- show the
    # four metrics that actually discriminate (the rest are in Table 4 / 5)
    panels = [("f1", "classic F1"), ("generalization", "generalisation"),
              ("simplicity", "simplicity"), ("translucent_f1", "translucent F1")]
    panels = [(c, t) for c, t in panels if c in e2.columns]
    methods = [m for m in QUALITY_ROWS if m in set(e2.method)]

    fig, axes = plt.subplots(2, 2, figsize=(11.6, 0.27 * len(methods) + 1.2))
    flat = list(np.atleast_1d(axes).flat)
    for ax, (col, title) in zip(flat, panels):
        piv = (e2.pivot_table(index="method", columns="log", values=col, aggfunc="mean")
               .reindex(methods))
        im = _heatmap(ax, piv, cmap="RdYlGn", norm=mcolors.Normalize(0.4, 1.0),
                      fmt="{:.2f}", title=title, label_fs=6.0, annot_fs=5.4)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02).ax.tick_params(labelsize=5)
    for ax in flat[len(panels):]:
        ax.set_visible(False)
    fig.suptitle("Model quality per log, all approaches (method $\\times$ log; cf. Fig. 3)",
                 fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    _save(fig, figdir, "fig_quality_perlog")


# --------------------------------------------------------------------------- #
# E5 -- scenario case study (ServiceDesk desktop workflow, noise sweep)
# --------------------------------------------------------------------------- #
_SCEN_METRICS = [
    ("ari", "ARI"), ("nmi", "NMI"), ("purity", "purity"),
    ("precision", "precision"), ("f1", "F1"), ("generalization", "generalisation"),
    ("simplicity", "simplicity"), ("translucent_fitness", "translucent fitness"),
    ("translucent_precision", "translucent precision"), ("translucent_f1", "translucent F1"),
]
_SCEN_CF = ["cf_kmeans@k", "cf_ward@k", "ctx_kmeans@k", "trace2vec@k", "enabled@k"]


def fig_scenario(e5: pd.DataFrame, figdir: Path) -> None:
    """Line-panel grid: one panel per metric, metric vs. enabled-set noise.
    kappa bold; the five k=GT clustering baselines as a min-max band; attr_clean,
    classical/translucent variants and global as named lines."""
    from evaluation.metrics_eval import harmonic_f1
    e5 = e5.copy()
    if "f1" not in e5:
        e5["f1"] = [harmonic_f1(a, b) for a, b in zip(e5.fitness, e5.precision)]
    noises = sorted(e5.noise.unique())
    metrics = [(c, lab) for c, lab in _SCEN_METRICS if c in e5.columns]
    nc = 5
    nr = (len(metrics) + nc - 1) // nc
    fig, axes = plt.subplots(nr, nc, figsize=(2.5 * nc, 2.3 * nr + 0.7), squeeze=False)

    def series(method, col):
        s = e5[e5.method == method].groupby("noise")[col].mean()
        return [s.get(nz, np.nan) for nz in noises]

    for ax, (col, lab) in zip(axes.flat, metrics):
        band = e5[e5.method.isin(_SCEN_CF)].groupby("noise")[col]
        lo, hi, mn = band.min(), band.mean(), band.max()
        ax.fill_between(noises, [lo.get(n, np.nan) for n in noises],
                        [mn.get(n, np.nan) for n in noises], color=ORANGE, alpha=0.16, lw=0)
        ax.plot(noises, [hi.get(n, np.nan) for n in noises], "-", color=ORANGE, lw=0.9,
                label="clustering (5, $k$=GT)")
        ax.plot(noises, series("global", col), "-", color="#333", lw=0.8, label="global")
        ax.plot(noises, series("classical_variants", col), ":", color=GREY, lw=1.1,
                label="classical variants")
        ax.plot(noises, series("translucent_variants", col), "-.", color=GREY, lw=1.1,
                label="translucent variants")
        ax.plot(noises, series("attr_clean@k", col), "--", color=BLUE, lw=1.2,
                label="attr clean ($k$=GT)")
        ax.plot(noises, series("kappa", col), "-o", color=GREEN, lw=1.8, ms=3,
                label=r"$\kappa$ (ours)")
        ax.set_title(lab, fontsize=8)
        ax.set_ylim(-0.03, 1.03)
        ax.tick_params(labelsize=6)
    for ax in list(axes.flat)[len(metrics):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("enabled-set noise", fontsize=7)
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=7, frameon=False, fontsize=7,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("ServiceDesk case study: every approach vs. enabled-set noise", fontsize=10)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    _save(fig, figdir, "fig_scenario")


def fig_scenario_heat(e5: pd.DataFrame, figdir: Path) -> None:
    """2x2 method x noise heatmaps for the headline metrics -- every approach visible."""
    import matplotlib.colors as mcolors
    from evaluation.metrics_eval import harmonic_f1
    e5 = e5.copy()
    if "f1" not in e5:
        e5["f1"] = [harmonic_f1(a, b) for a, b in zip(e5.fitness, e5.precision)]
    panels = [("ari", "ARI", mcolors.Normalize(0.0, 1.0)),
              ("translucent_f1", "translucent F1", mcolors.Normalize(0.4, 1.0)),
              ("translucent_fitness", "translucent fitness", mcolors.Normalize(0.4, 1.0)),
              ("precision", "precision", mcolors.Normalize(0.4, 1.0))]
    rows = [m for m in QUALITY_ROWS if m in set(e5.method)]
    fig, axes = plt.subplots(2, 2, figsize=(10.6, 0.30 * len(rows) + 1.2))
    for ax, (col, title, nrm) in zip(axes.flat, panels):
        piv = (e5.pivot_table(index="method", columns="noise", values=col, aggfunc="mean")
               .reindex(rows))
        im = _heatmap(ax, piv, cmap="RdYlGn", norm=nrm, fmt="{:.2f}", title=title,
                      label_fs=6.2, annot_fs=5.6)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02).ax.tick_params(labelsize=5)
    fig.suptitle("ServiceDesk case study: approach $\\times$ noise", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    _save(fig, figdir, "fig_scenario_heat")


def render_all(e1: pd.DataFrame, e2: pd.DataFrame, e3: pd.DataFrame, figdir: Path,
               attr_df: "pd.DataFrame | None" = None,
               e5: "pd.DataFrame | None" = None) -> None:
    fig_separation(e1, figdir)
    fig_recovery(e1, figdir)
    fig_enabled_incoherence(e1, figdir)
    fig_perlog(e1, figdir)
    fig_quality(e2, figdir)
    fig_quality_perlog(e2, figdir)
    fig_compactness(e2, figdir)
    if not e3.empty:
        fig_noise(e3, figdir)
    if attr_df is not None and not attr_df.empty:
        fig_attributes(attr_df, figdir)
    if e5 is not None and not e5.empty:
        fig_scenario(e5, figdir)
        fig_scenario_heat(e5, figdir)


__all__ = [
    "fig_separation", "fig_recovery", "fig_enabled_incoherence", "fig_perlog",
    "fig_quality", "fig_quality_perlog", "fig_compactness", "fig_noise",
    "fig_attributes", "fig_scenario", "fig_scenario_heat", "render_all",
]
