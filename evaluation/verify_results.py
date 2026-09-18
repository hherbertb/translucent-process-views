"""Independent check of every number in the paper's result tables.

Recomputes each table cell straight from the per-run CSVs in ``evaluation/results/``
with explicit two-stage means (seed -> log -> overall), without importing any
aggregation code from ``run_evaluation.py`` or ``run_semireal.py``, and compares
the result with the cells of the LaTeX tables the paper actually inputs.

A cell passes if it agrees to the printed precision.  Everything else is listed.

    venv/Scripts/python evaluation/verify_results.py "paper_final/<project>"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RES = Path(__file__).resolve().parent / "results"

# the nine synthetic logs of Table 1, spelled out here rather than imported
NINE = ["running_example", "k_view_k2", "k_view_k3", "k_view_k4", "k_view_k5",
        "partial_parallel", "enterprise", "hidden_context", "loop_process"]

LABEL = {
    "global": "global", "kappa": r"$\kappa$ (ours)",
    "kappa_supported": r"$\kappa$ + support (ours)",
    "cf_kmeans@k": r"CF-TC $k$-means (GT)", "cf_kmeans@auto": r"CF-TC $k$-means (auto)",
    "cf_ward@k": "CF-TC Ward (GT)", "cf_ward@auto": "CF-TC Ward (auto)",
    "ctx_kmeans@k": "CTX-TC (GT)", "ctx_kmeans@auto": "CTX-TC (auto)",
    "enabled@k": "EN-TC (GT)", "enabled@auto": "EN-TC (auto)",
    "trace2vec@k": "D2V-TC (GT)", "trace2vec@auto": "D2V-TC (auto)",
    "attr_clean@k": "ATTR-TC clean (GT)", "attr_clean@auto": "ATTR-TC clean (auto)",
    "attr_noisy@k": "ATTR-TC noisy (GT)", "attr_noisy@auto": "ATTR-TC noisy (auto)",
    "attr_all@k": "ATTR-TC all (GT)", "attr_all@auto": "ATTR-TC all (auto)",
    "classical_variants": "variant discovery",
    "translucent_variants": "translucent-variant grouping",
    "attr_oracle@k": r"ATTR-TC oracle (GT)$^{\dagger}$",
}


def _expand_labels(label_map: dict) -> dict:
    """A paired row prints "CF-TC Ward", not "CF-TC Ward (GT)": accept both."""
    out = dict(label_map)
    for method, label in label_map.items():
        if method.endswith("@k") and label.endswith(" (GT)"):
            out.setdefault(method + "#plain", label[: -len(" (GT)")])
    return out


def parse_tex(path: Path) -> "dict[str, list[str]]":
    """Row label -> list of cell strings, with \\textbf and $ stripped."""
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "&" not in line or r"\\" not in line:
            continue
        cells = [c.strip() for c in line.split(r"\\")[0].split("&")]
        label = cells[0]
        if not label:
            continue
        clean = [re.sub(r"\\textbf\{([^}]*)\}", r"\1", c).strip() for c in cells[1:]]
        rows[label] = clean
    return rows


def two_stage(df: pd.DataFrame, col: str, by_seed: bool) -> "pd.Series":
    """Mean over seeds within each (log, method), then mean over logs per method."""
    keys = ["log", "method"]
    if by_seed:
        per_log = df.groupby(keys + ["seed"])[col].mean().groupby(keys).mean()
    else:
        per_log = df.groupby(keys)[col].mean()
    return per_log.groupby("method").mean()


problems: "list[str]" = []
checked = 0


def compare(table: str, label: str, col: str, printed: str, value: float) -> None:
    global checked
    checked += 1
    if printed in ("--", ""):
        if not (value is None or (isinstance(value, float) and np.isnan(value))):
            problems.append(f"{table:8s} {label:32s} {col:12s} printed '--' but data = {value}")
        return
    try:
        p = float(printed)
    except ValueError:
        problems.append(f"{table:8s} {label:32s} {col:12s} unparseable cell {printed!r}")
        return
    decimals = len(printed.split(".")[1]) if "." in printed else 0
    tol = 0.5 * 10 ** -decimals + 1e-9
    if value is None or np.isnan(value) or abs(p - value) > tol:
        problems.append(f"{table:8s} {label:32s} {col:12s} printed {printed:>8s}  recomputed {value:.4f}")


def main(project: Path) -> int:
    tables = project / "tables"
    inv = {v: k.replace('#plain', '') for k, v in _expand_labels(LABEL).items()}

    # ---------------------------------------------------------------- Table 2
    e1 = pd.read_csv(RES / "e1_separation.csv")
    e1 = e1[e1.log.isin(NINE)]
    missing = sorted(set(NINE) - set(e1.log))
    if missing:
        problems.append(f"Table 2: logs missing from e1: {missing}")
    # every (log, method) must have all seeds, or pooled and two-stage means disagree
    cnt = e1.groupby(["log", "method"]).seed.nunique()
    if cnt.min() != cnt.max():
        problems.append(f"Table 2: unbalanced seeds per (log, method): {cnt[cnt != cnt.max()].to_dict()}")
    # the paper now inputs one merged table; its first four numeric columns are
    # the recovery half, the rest the quality half
    merged = tables / "summary_combined_table.tex"
    t2 = parse_tex(merged if merged.exists() else tables / "summary_partition_table.tex")
    for label, cells in t2.items():
        m = inv.get(label)
        if m is None:
            problems.append(f"Table 2: unknown row label {label!r}")
            continue
        for col, printed in zip(("ari", "nmi", "purity", "sig_per_variant"), cells):
            if "/" in printed:          # "GT / auto": check both halves
                gt_txt, auto_txt = [x.strip() for x in printed.split("/")]
                auto = f"{m.split('@')[0]}@auto"
                compare("Table 2", label, col, gt_txt, two_stage(e1, col, True).get(m, np.nan))
                compare("Table 2", label + " (auto)", col, auto_txt,
                        two_stage(e1, col, True).get(auto, np.nan))
            else:
                compare("Table 2", label, col, printed, two_stage(e1, col, True).get(m, np.nan))

    # ---------------------------------------------------------------- Table 3
    e2 = pd.read_csv(RES / "e2_quality.csv")
    e2 = e2[e2.log.isin(NINE)]
    t3 = parse_tex(merged) if merged.exists() else parse_tex(tables / "summary_quality_table.tex")
    q_offset = 4 if merged.exists() else 0
    q_cols = ("n_models", "precision", "f1", "generalization", "simplicity",
              "translucent_fitness", "translucent_precision", "translucent_f1")
    for label, cells in t3.items():
        m = inv.get(label)
        if m is None:
            problems.append(f"Table 3: unknown row label {label!r}")
            continue
        for col, printed in zip(q_cols, cells[q_offset:]):
            compare("Table 3", label, col, printed, two_stage(e2, col, False).get(m, np.nan))
    fit = e2[e2.method.isin([inv[l] for l in t3 if l in inv])].fitness
    if not np.allclose(fit, 1.0):
        problems.append(f"Table 3: prose says fitness is 1.00 everywhere, min is {fit.min():.4f}")

    # ---------------------------------------------------------------- Table 4
    e5 = pd.read_csv(RES / "e5_case_study.csv")
    e5 = e5[e5.noise_mode == "balanced"]   # the mode Sect. 5.4 describes
    t4 = parse_tex(tables / "case_study_table.tex")
    head = [l for l in (tables / "case_study_table.tex").read_text(encoding="utf-8").splitlines()
            if "ARI" in l][0]
    levels = [float(x) for x in re.findall(r"ARI \$p\{?=\}?([0-9.]+)\$", head)]
    if not levels:
        levels = [float(x) for x in re.findall(r"p=([0-9.]+)", head)][::2]
    for label, cells in t4.items():
        m = inv.get(label)
        if m is None:
            problems.append(f"Table 4: unknown row label {label!r}")
            continue
        for i, p in enumerate(levels):
            sub = e5[(e5.method == m) & np.isclose(e5.noise, p)]
            ari = sub.groupby("seed").ari.mean().mean() if len(sub) else np.nan
            compare("Table 4", label, f"ARI p={p}", cells[2 * i], ari)
            if "translucent_f1" in sub:
                tf1 = sub.groupby("seed").translucent_f1.mean().mean() if len(sub) else np.nan
                compare("Table 4", label, f"trF1 p={p}", cells[2 * i + 1], tf1)
            if len(sub) and sub.seed.nunique() != 3:
                problems.append(f"Table 4: {label} p={p} has {sub.seed.nunique()} seeds, caption says three")

    # ---------------------------------------------------------------- Table 5
    s1 = pd.read_csv(RES / "s1_semireal.csv")
    s1 = s1[~s1.attribute.str.startswith("(control")]
    t5 = parse_tex(tables / "semireal_table.tex")
    base = {"CF-TC $k$-means": "cf_kmeans", "CF-TC Ward": "cf_ward", "CTX-TC": "ctx_kmeans",
            "EN-TC": "enabled", "D2V-TC": "trace2vec"}
    single = {"global": "global", r"$\kappa$ (ours)": "kappa",
              r"$\kappa$ + support (ours)": "kappa_supported",
              r"$\kappa_{\mathit{av}}$ (ours)": "kappa_acts",
              "variant discovery": "classical_variants",
              "translucent-variant grouping": "translucent_variants"}
    for label, cells in t5.items():
        if label in ("", "ARI"):
            continue
        for li, lg in enumerate(("hospital_billing", "road_traffic")):
            s = s1[s1.log == lg].set_index("method")
            for ci, col in enumerate(("ari", "n_groups")):
                cell = cells[2 * li + ci]
                if label in single:
                    compare("Table 5", label, f"{lg[:8]} {col}", cell, float(s.loc[single[label], col]))
                elif label in base:
                    gt, au = [x.strip() for x in cell.split("/")]
                    compare("Table 5", label + " GT", f"{lg[:8]} {col}", gt, float(s.loc[base[label] + "@k", col]))
                    compare("Table 5", label + " auto", f"{lg[:8]} {col}", au, float(s.loc[base[label] + "@auto", col]))
                else:
                    problems.append(f"Table 5: unknown row label {label!r}")

    print(f"checked {checked} table cells against the raw per-run CSVs")
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print("  " + p)
        return 1
    print("OK: every cell agrees with an independent recomputation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
