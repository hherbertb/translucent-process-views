"""Run only experiment E5 (the service-desk case study) and write its CSV.

The full harness reruns every experiment, which takes hours; this reruns the one
experiment whose generator changed.  Afterwards rebuild the paper tables with

    venv/Scripts/python evaluation/run_evaluation.py --tables-only --paper-out <dir>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import evaluation.run_evaluation as RE  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "results"))
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df = RE.experiment_case_study(False, True, list(range(a.seeds)))
    df.to_csv(out / "e5_case_study.csv", index=False)
    print(f"wrote {out / 'e5_case_study.csv'} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()   # set-iteration order must not vary between runs
    raise SystemExit(main())
