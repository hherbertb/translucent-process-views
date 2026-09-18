"""Screen event logs for a case attribute that could play the hidden context.

The semi-real experiment needs an attribute that (a) splits the log into a few
groups of usable size and (b) actually gates behaviour -- if the per-group models
coincide there is nothing to recover, and if the executed sequences already
determine the group the experiment says nothing about enabled activities.

For every candidate attribute this prints:

  groups      the kept values and their case counts
  balance     share of the largest group (road traffic's 0.98 is what to avoid)
  jaccard     min..max directly-follows overlap between groups
              (low = the groups behave differently = something to recover)
  var-overlap share of cases whose classical variant occurs in >1 group
              (high = executed activities alone do not determine the group)

    venv/Scripts/python evaluation/scan_logs.py --logs "BPI_Challenge_2013_incidents.xes"
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MAX_GROUPS = 4
MIN_SHARE = 0.02          # a group smaller than this cannot carry a model


def footprint(seqs):
    return {(a, b) for s in seqs for a, b in zip(s, s[1:])}


def scan(path: Path, top: int = MAX_GROUPS) -> None:
    import pandas as pd
    import pm4py

    print(f"\n=== {path.name}", flush=True)
    d = pm4py.read_xes(str(path), return_legacy_log_object=False)
    d = d.dropna(subset=["concept:name", "case:concept:name"])
    d = d.sort_values(["case:concept:name", "time:timestamp"], kind="stable")
    cases = (d.groupby("case:concept:name")["concept:name"]
             .apply(lambda s: tuple(s)).to_dict())
    print(f"  {len(cases):,} cases, {d['concept:name'].nunique()} activities")

    skip = {"concept:name", "time:timestamp", "case:concept:name", "lifecycle:transition",
            "org:resource", "start_timestamp", "@@index", "@@case_index"}
    for col in d.columns:
        if col in skip or d[col].dtype.kind in "fM":
            continue
        per_case = d.groupby("case:concept:name")[col].agg(
            lambda s: s.dropna().iloc[0] if s.notna().any() else None).dropna()
        if per_case.empty:
            continue
        vc = per_case.astype(str).value_counts()
        if not (2 <= len(vc) <= 60):
            continue
        keep = vc.head(top)
        if keep.iloc[-1] / len(cases) < MIN_SHARE:
            continue
        groups = {c: v for c, v in per_case.astype(str).items()
                  if v in set(keep.index) and c in cases}
        if len(set(groups.values())) < 2:
            continue
        by = {}
        for cid, g in groups.items():
            by.setdefault(g, []).append(cases[cid])
        fps = {g: footprint(v) for g, v in by.items()}
        labels = sorted(by)
        jac = [len(fps[a] & fps[b]) / max(1, len(fps[a] | fps[b]))
               for i, a in enumerate(labels) for b in labels[i + 1:]]
        var_groups = {}
        for cid, g in groups.items():
            var_groups.setdefault(cases[cid], set()).add(g)
        shared = {v for v, gs in var_groups.items() if len(gs) > 1}
        overlap = sum(1 for cid in groups if cases[cid] in shared) / max(1, len(groups))
        sizes = {g: len(v) for g, v in by.items()}
        balance = max(sizes.values()) / sum(sizes.values())
        print(f"  {col:28s} groups {sizes}")
        print(f"  {'':28s} balance {balance:.2f}  jaccard {min(jac):.2f}..{max(jac):.2f}"
              f"  var-overlap {overlap:.1%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"C:/Users/beyel/Documents/Code/cabumm/data")
    ap.add_argument("--logs", nargs="*", default=None)
    a = ap.parse_args()
    root = Path(a.dir)
    names = a.logs or [p.name for p in sorted(root.glob("*.xes"))]
    for n in names:
        try:
            scan(root / n, MAX_GROUPS)
        except Exception as e:                        # keep screening the rest
            print(f"  ! {n}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()
    raise SystemExit(main())
