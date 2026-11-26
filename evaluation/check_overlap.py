"""Is a log able to demonstrate what the method claims?

The method's claim is that the *enabled* activities reveal a context that the
*executed* activities do not.  A log can only support that claim if the same
executed behaviour occurs under more than one value of the hidden context --
otherwise the activity names already answer the question and the enabled sets
are redundant.  Sect. 5.5 of the paper states the property for the two public
logs: "at least 99 % of cases lie in classical variants shared between groups,
so execution alone does not determine it".

This script measures that property, and the headroom it leaves, on any event
table.  Run it *before* a generation run at scale.

    python evaluation/check_overlap.py <events.csv> [--label role] [--unit segment]

The gate is a *count* of contested traces, not a fraction.  The fraction is
what the two public logs are described by (>= 99 %), but it is the wrong bar
for a generated log: in Odoo most steps are legitimately role-private, so the
fraction stays at 7-11 % however the scenario is written, while the statistic
that actually has to hold still -- the ARI restricted to the contested traces
-- depends on how many contested traces there are.  Measured across three runs
of ``p2p_shared``, 8 contested traces gave a baseline ARI of -0.149, 16 gave
0.200 and 24 gave -0.038: the same quantity, moving by half its range.  So the
gate asks for enough contested traces to estimate anything, and reports the
fraction without gating on it.

``--unit case``     one trace per case, label = the case's (single) label
``--unit segment``  split each case into maximal runs of consecutive events by
                    one label value; one trace per run.  Use this when the
                    context changes hands inside a case, as with Odoo roles.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict

import pandas as pd

try:
    from sklearn.metrics import adjusted_rand_score
except ImportError:  # pragma: no cover
    adjusted_rand_score = None


def segments(df: pd.DataFrame, label: str, case: str, act: str, order: str):
    """Maximal runs of consecutive events sharing one label value."""
    out = []
    for _, g in df.groupby(case):
        g = g.sort_values(order)
        cur, lab = [], None
        for _, r in g.iterrows():
            if r[label] != lab:
                if cur:
                    out.append((lab, tuple(cur)))
                cur, lab = [], r[label]
            cur.append(r[act])
        if cur:
            out.append((lab, tuple(cur)))
    return out


def whole_cases(df: pd.DataFrame, label: str, case: str, act: str, order: str):
    out = []
    for _, g in df.groupby(case):
        g = g.sort_values(order)
        labs = set(g[label])
        if len(labs) != 1:
            raise SystemExit(
                f"--unit case needs one {label!r} per {case!r}; found {len(labs)}. "
                f"Use --unit segment.")
        out.append((labs.pop(), tuple(g[act])))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("events")
    p.add_argument("--label", default="role", help="column holding the hidden context")
    p.add_argument("--case", default="case_id")
    p.add_argument("--activity", default="activity")
    p.add_argument("--order", default="seq")
    p.add_argument("--unit", choices=("case", "segment"), default="segment")
    p.add_argument("--min-contested", type=int, default=100,
                   help="traces in a shared executed sequence needed to PASS")
    p.add_argument("--warn-contested", type=int, default=30,
                   help="below --min-contested but at or above this: THIN")
    a = p.parse_args()

    df = pd.read_csv(a.events)
    for col in (a.label, a.case, a.activity, a.order):
        if col not in df.columns:
            raise SystemExit(f"column {col!r} not in {a.events}")

    traces = (segments if a.unit == "segment" else whole_cases)(
        df, a.label, a.case, a.activity, a.order)
    if not traces:
        raise SystemExit("no traces")

    # --- does one activity ever appear under two labels? ---------------------
    by_act = defaultdict(set)
    for lab, seq in traces:
        for act in seq:
            by_act[act].add(lab)
    shared_acts = {k: v for k, v in by_act.items() if len(v) > 1}

    # --- do whole executed sequences recur under two labels? -----------------
    by_seq = defaultdict(Counter)
    for lab, seq in traces:
        by_seq[seq][lab] += 1
    shared_seqs = {s: c for s, c in by_seq.items() if len(c) > 1}
    n_shared = sum(sum(c.values()) for c in shared_seqs.values())
    frac = n_shared / len(traces)

    labels = sorted({lab for lab, _ in traces})
    print(f"{a.events}")
    print(f"  unit                      {a.unit}   traces {len(traces)}   "
          f"{a.label} values {len(labels)}")
    print(f"  activities under >1 {a.label:<6}{len(shared_acts)} of {len(by_act)}")
    print(f"  executed seqs under >1 {a.label:<3}{len(shared_seqs)} of {len(by_seq)}")
    print(f"  traces in a shared seq    {n_shared} / {len(traces)}  = {frac:.1%}")

    # --- the bar the method has to clear -------------------------------------
    if adjusted_rand_score is not None:
        truth = [lab for lab, _ in traces]
        blind = [hash(seq) for _, seq in traces]
        print(f"  ARI of executed sequence alone (uses NO enabled info): "
              f"{adjusted_rand_score(truth, blind):.3f}")

    if shared_acts:
        print("\n  shared activities (where the enabled sets must do the work):")
        for act, labs in sorted(shared_acts.items(), key=lambda kv: -len(kv[1]))[:12]:
            print(f"     {act:<30} {sorted(labs)}")

    if n_shared >= a.min_contested:
        verdict, rc = "PASS", 0
    elif n_shared >= a.warn_contested:
        verdict, rc = "THIN", 0
    else:
        verdict, rc = "FAIL", 1
    print(f"\n  VERDICT: {verdict} -- {n_shared} traces sit in a shared executed "
          f"sequence ({frac:.1%} of {len(traces)}); PASS needs >= {a.min_contested}, "
          f"THIN >= {a.warn_contested}.")
    if verdict == "THIN":
        print("  Enough to see an effect, not enough to report a number: the ARI on\n"
              "  the contested traces alone will move by a large fraction of its\n"
              "  range between seeds.  Scale the run up before quoting it.")
    if verdict == "FAIL":
        print("  The executed activities already determine the context, so this log\n"
              "  cannot show that the enabled activities add anything.  Either the\n"
              "  roles need overlapping work, or the overlap needs to be placed\n"
              "  where their access rights differ.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
