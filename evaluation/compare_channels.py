"""Does the enabled information buy anything on this log?

Runs kappa over each enabled-activity channel of an Odoo simulation log and
compares it against a baseline that sees only the executed activities.  The
executed projection is identical across channels, so any difference is caused
by the enabled sets alone.

    python evaluation/compare_channels.py <events.csv> [--unit segment]

Channels (columns, if present):
    enabled_activities_gui            what the screen offered
    enabled_activities_backend        what the server would accept, this document
    enabled_activities_backend_case   ... over every document of the case
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tpv.views.views import kappa  # noqa: E402

CHANNELS = [
    ("enabled_activities_gui", "GUI (screen)"),
    ("enabled_activities_backend", "backend / document"),
    ("enabled_activities_backend_case", "backend / case"),
]


def parse_set(value) -> frozenset:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return frozenset()
    return frozenset(x.strip() for x in str(value).split(",") if x.strip())


def build(df: pd.DataFrame, label: str, case: str, act: str, order: str, unit: str):
    """-> list of (label_value, [row, ...])"""
    out = []
    for _, g in df.groupby(case):
        g = g.sort_values(order)
        if unit == "case":
            labs = set(g[label])
            out.append((labs.pop() if len(labs) == 1 else "<mixed>", list(g.itertuples())))
            continue
        cur, lab = [], None
        for row in g.itertuples():
            if getattr(row, label) != lab:
                if cur:
                    out.append((lab, cur))
                cur, lab = [], getattr(row, label)
            cur.append(row)
        if cur:
            out.append((lab, cur))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("events")
    p.add_argument("--label", default="role")
    p.add_argument("--case", default="case_id")
    p.add_argument("--activity", default="activity")
    p.add_argument("--order", default="seq")
    p.add_argument("--unit", choices=("case", "segment"), default="segment")
    a = p.parse_args()

    df = pd.read_csv(a.events)
    traces = build(df, a.label, a.case, a.activity, a.order, a.unit)
    truth = [lab for lab, _ in traces]
    print(f"{a.events}")
    print(f"  unit {a.unit}   traces {len(traces)}   {a.label} values {len(set(truth))}\n")

    blind = [hash(tuple(getattr(r, a.activity) for r in rows)) for _, rows in traces]
    print(f"  {'grouping':<34}{'groups':>7}{'ARI':>8}{'NMI':>8}")
    print(f"  {'executed sequence (no enabled info)':<34}{len(set(blind)):>7}"
          f"{adjusted_rand_score(truth, blind):>8.3f}{normalized_mutual_info_score(truth, blind):>8.3f}")

    for col, name in CHANNELS:
        if col not in df.columns:
            continue
        labs = []
        for _, rows in traces:
            sigma = tuple((getattr(r, a.activity), parse_set(getattr(r, col))) for r in rows)
            labs.append(kappa(sigma).canonical_str())
        print(f"  {'kappa / ' + name:<34}{len(set(labs)):>7}"
              f"{adjusted_rand_score(truth, labs):>8.3f}"
              f"{normalized_mutual_info_score(truth, labs):>8.3f}")

    # where the executed sequence is ambiguous, does the enabled set resolve it?
    from collections import Counter, defaultdict
    by_seq = defaultdict(Counter)
    for (lab, rows), b in zip(traces, blind):
        by_seq[b][lab] += 1
    contested = {s for s, c in by_seq.items() if len(c) > 1}
    idx = [i for i, b in enumerate(blind) if b in contested]
    print(f"\n  contested traces (same executed sequence, >1 {a.label}): "
          f"{len(idx)} / {len(traces)} = {len(idx)/len(traces):.1%}")
    if idx:
        for col, name in CHANNELS:
            if col not in df.columns:
                continue
            labs = []
            for i in idx:
                _, rows = traces[i]
                sigma = tuple((getattr(r, a.activity), parse_set(getattr(r, col))) for r in rows)
                labs.append(kappa(sigma).canonical_str())
            t = [truth[i] for i in idx]
            print(f"     kappa / {name:<26} ARI on contested only {adjusted_rand_score(t, labs):>7.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
