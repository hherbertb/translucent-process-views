"""Clean-room check of kappa and the recovery metrics against the recorded results.

Nothing from ``tpv.views`` or ``evaluation.metrics_eval`` is imported.  kappa is
re-implemented directly from Definitions 4.2-4.10 of the paper; ARI and NMI come
from scikit-learn, purity and enabled-signature incoherence are written out by
hand.  Only the log generator is shared, since it defines the data.

Checks, for every synthetic log of Table 1 and every seed in e1_separation.csv:
  * Table 1 columns (cases, activities, average length, variants, kappa views);
  * that this kappa induces exactly the same partition as the library's kappa;
  * ARI / NMI / purity / incoherence of global, kappa, variant and
    translucent-variant grouping against the recorded rows.

    venv/Scripts/python evaluation/verify_independent.py "paper_final/<project>"
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tpv.log.synth import build_all  # noqa: E402  (data only)

NINE = ["running_example", "k_view_k2", "k_view_k3", "k_view_k4", "k_view_k5",
        "partial_parallel", "enterprise", "hidden_context", "loop_process"]


# --------------------------------------------------------------------------- #
# kappa, straight from the definitions.  An event is (executed, enabled set).
# --------------------------------------------------------------------------- #
def kappa(sigma) -> object:
    n = len(sigma)
    if n == 0:
        return "eps"                                                  # Def. 4.10
    act = [e[0] for e in sigma]
    en = [frozenset(e[1]) for e in sigma]

    def next_en(i):                                                   # Def. 4.2
        return en[i + 1] if i < n - 1 else frozenset()

    choice = [frozenset({act[i]}) | (en[i] - next_en(i)) for i in range(n)]  # Def. 4.3

    def block(i):                                                     # Def. 4.4
        return act[i] if len(choice[i]) == 1 else ("xor", choice[i])

    def supports(i, j):                                               # Def. 4.6
        return not (choice[i] & choice[j]) and choice[j] <= (en[i] & next_en(i))

    def par_supported(p, q):                                          # Def. 4.7
        return p < q and all(supports(i, j) for i in range(p, q + 1)
                             for j in range(i + 1, q + 1))

    intervals, p = [], 0                                              # Def. 4.8
    while p < n:
        qs = [q for q in range(p + 1, n) if par_supported(p, q)]
        q = max(qs) if qs else p
        intervals.append((p, q))
        p = q + 1

    def abs_(p, q):                                                   # Def. 4.9
        return block(p) if p == q else ("and", frozenset(block(i) for i in range(p, q + 1)))

    parts = [abs_(p, q) for p, q in intervals]
    return parts[0] if len(parts) == 1 else ("seq", tuple(parts))    # Def. 4.10


# --------------------------------------------------------------------------- #
def cases_of(log):
    """(case id, trace) for every case -- the multiset L expanded."""
    for t, ids in log.case_ids.items():
        for cid in ids:
            yield cid, t


def purity(true, pred):
    by = defaultdict(Counter)
    for a, b in zip(true, pred):
        by[b][a] += 1
    return sum(c.most_common(1)[0][1] for c in by.values()) / len(true)


def incoherence(pairs):
    """Mean number of distinct enabled-set sequences per (group, classical variant)."""
    sigs = defaultdict(set)
    for g, t in pairs:
        sigs[(g, tuple(e[0] for e in t))].add(tuple(frozenset(e[1]) for e in t))
    return float(np.mean([len(s) for s in sigs.values()]))


def main(project: Path) -> int:
    e1 = pd.read_csv(ROOT / "evaluation/results/e1_separation.csv").set_index(["log", "seed", "method"])
    t1 = {}
    for line in (project / "tables/logs_overview_table.tex").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("\\\\")[0].split("&")]
        if len(cells) == 8 and cells[1].isdigit():
            t1[cells[0]] = cells[1:]
    display = {"running_example": "running example", "k_view_k2": "$k$-view ($k{=}2$)",
               "k_view_k3": "$k$-view ($k{=}3$)", "k_view_k4": "$k$-view ($k{=}4$)",
               "k_view_k5": "$k$-view ($k{=}5$)", "partial_parallel": "parallel choices",
               "enterprise": "enterprise", "hidden_context": "role split",
               "loop_process": "rework loop"}

    bad, n_cmp = [], 0
    seeds = sorted(set(e1.index.get_level_values("seed")))
    for seed in seeds:
        for name, log, gt, _ in build_all(False, seed=seed):
            if name not in NINE:
                continue
            cases = list(cases_of(log))
            traces = sorted(set(t for _, t in cases), key=repr)
            mine = {t: kappa(t) for t in traces}

            # same partition as the library's kappa (compared as sets of trace sets)
            from tpv.views.views import induce_views          # the one library call, for comparison
            lib = {frozenset(v.traces) for v in induce_views(log)}
            ours = defaultdict(set)
            for t, ident in mine.items():
                ours[ident].add(t)
            if lib != {frozenset(s) for s in ours.values()}:
                bad.append(f"{name} seed {seed}: clean-room kappa partition differs from library "
                           f"({len(ours)} vs {len(lib)} views)")

            if seed == 0:                                       # Table 1 is built from seed 0
                row = t1.get(display[name])
                lens = [len(t) for _, t in cases]
                acts = {e[0] for t in traces for e in t} | {a for t in traces for e in t for a in e[1]}
                calc = [str(len(cases)), str(len(acts)), f"{np.mean(lens):.1f}",
                        str(len({tuple(e[0] for e in t) for t in traces})), str(len(traces)),
                        str(len(set(gt.values()))) if gt else "--", str(len(ours))]
                if row is None:
                    bad.append(f"Table 1: no row for {display[name]}")
                else:
                    for h, printed, c in zip(("cases", "acts", "avg len", "class var", "transl var",
                                              "hidden k", "kappa views"), row, calc):
                        n_cmp += 1
                        if printed != c:
                            bad.append(f"Table 1 {display[name]:22s} {h:11s} printed {printed}  recomputed {c}")

            # label by identifier *equality*, never repr(): equal frozensets can print in
            # different orders, which would split one view into several
            view_id = {ident: i for i, ident in enumerate(ours)}
            groupings = {
                "global": {t: 0 for t in traces},
                "kappa": {t: view_id[mine[t]] for t in traces},
                "classical_variants": {t: tuple(e[0] for e in t) for t in traces},
                "translucent_variants": {t: i for i, t in enumerate(traces)},
            }
            for meth, g in groupings.items():
                pred = [repr(g[t]) for _, t in cases]
                rec = e1.loc[(name, seed, meth)]
                vals = {"n_groups": len(set(g.values())),
                        "sig_per_variant": incoherence((g[t], t) for t in traces)}
                if gt:
                    true = [gt[cid] for cid, _ in cases]
                    vals.update(ari=adjusted_rand_score(true, pred),
                                nmi=normalized_mutual_info_score(true, pred),
                                purity=purity(true, pred))
                for c, v in vals.items():
                    n_cmp += 1
                    if abs(float(rec[c]) - v) > 1e-9:
                        bad.append(f"{name:18s} seed {seed} {meth:22s} {c:16s} recorded {rec[c]:.6f}  independent {v:.6f}")

    print(f"clean-room check: {len(seeds)} seeds x {len(NINE)} logs, {n_cmp} values compared")
    if bad:
        print(f"{len(bad)} mismatch(es):")
        for b in bad[:40]:
            print("  " + b)
        return 1
    print("OK: clean-room kappa matches the library on every log, and Table 1 and the "
          "recorded recovery metrics agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
