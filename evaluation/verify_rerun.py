"""Re-execute a sample of the recorded runs from scratch and compare with the CSVs.

``verify_results.py`` proves the tables agree with the CSVs; this proves the CSVs
agree with the code.  It regenerates a subset of logs for one seed, reruns every
grouping through the harness's own ``experiment_separation`` (restricted to that
subset) and the κ / baseline recovery of the case study without model quality,
and compares every recorded field row by row.

    venv/Scripts/python evaluation/verify_rerun.py [--logs a,b,c] [--seed 1]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evaluation.run_evaluation as RE  # noqa: E402
import tpv.log.synth as SY  # noqa: E402

RES = ROOT / "evaluation" / "results"
FIELDS = ["n_groups", "ari", "nmi", "purity", "sig_per_variant"]


def close(a, b, tol=1e-6) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= tol


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="running_example,hidden_context,enterprise")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--case", action="store_true", help="also rerun the case study (recovery only)")
    a = ap.parse_args()
    want = a.logs.split(",")

    real_build_all = SY.build_all

    def subset(quick=False, seed=None):
        for item in real_build_all(quick, seed=seed):
            if item[0] in want:
                yield item

    bad, n = [], 0
    if want != ["none"]:
        RE.build_all = subset
        fresh = RE.experiment_separation(False, [a.seed])
        old = pd.read_csv(RES / "e1_separation.csv")
        old = old[old.log.isin(want) & (old.seed == a.seed)]
        key = ["log", "method"]
        f = fresh.set_index(key)
        o = old.set_index(key)
        missing = sorted(set(o.index) ^ set(f.index))
        if missing:
            bad.append(f"rows present in only one of recorded / fresh: {missing}")
        for idx in sorted(set(o.index) & set(f.index)):
            for c in FIELDS:
                n += 1
                if not close(o.loc[idx, c], f.loc[idx, c]):
                    bad.append(f"{idx[0]:18s} {idx[1]:24s} {c:16s} recorded {o.loc[idx, c]}  fresh {f.loc[idx, c]}")
        print(f"E1 separation: re-executed {len(f)} runs ({len(want)} logs, seed {a.seed}), compared {n} values")

    if a.case:
        RE.build_all = real_build_all
        fresh5 = RE.experiment_case_study(False, False, [a.seed])
        old5 = pd.read_csv(RES / "e5_case_study.csv")
        old5 = old5[old5.seed == a.seed]
        k5 = ["noise", "noise_mode", "method"]
        f5, o5 = fresh5.set_index(k5), old5.set_index(k5)
        m5 = 0
        for idx in sorted(set(o5.index) & set(f5.index)):
            for c in ("n_groups", "ari", "nmi", "purity"):
                m5 += 1
                if not close(o5.loc[idx, c], f5.loc[idx, c]):
                    bad.append(f"E5 {idx}  {c}: recorded {o5.loc[idx, c]}  fresh {f5.loc[idx, c]}")
        only = sorted(set(o5.index) ^ set(f5.index))
        if only:
            bad.append(f"E5 rows present in only one of recorded / fresh: {only[:6]}")
        print(f"E5 case study: re-executed {len(f5)} runs (seed {a.seed}), compared {m5} values")

    if bad:
        print(f"{len(bad)} mismatch(es):")
        for b in bad:
            print("  " + b)
        return 1
    print("OK: fresh runs reproduce the recorded values exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
