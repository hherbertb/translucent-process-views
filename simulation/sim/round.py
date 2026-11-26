"""One full quality round: every scenario plus a mixed run, each run twice
with the same seed, then the quality analysis of each pair.

    python -m sim.round --seed 101
    python -m sim.round --seed 202 --cases 40 --mixed-cases 60 --parallel 4

Runs go to output/round_<seed>/<scenario>/ and .../<scenario>_repro/.
Runs are separate processes; up to --parallel of them work at the same time
(each has its own browser, scheduler and random streams, so they do not
influence each other's choices). Exit status 1 if any hard check failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .scenarios import CASES


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--cases", type=int, default=40, help="cases per single-scenario run")
    ap.add_argument("--mixed-cases", type=int, default=60)
    ap.add_argument("--concurrency", type=int, default=4, help="open cases per run")
    ap.add_argument("--parallel", type=int, default=4, help="runs executed at the same time")
    ap.add_argument("--only", nargs="*", default=None, help="subset of scenarios (and/or 'mixed')")
    ap.add_argument("--skip-runs", action="store_true", help="only (re)do the quality analysis")
    a = ap.parse_args()
    base = Path("output") / f"round_{a.seed}"
    base.mkdir(parents=True, exist_ok=True)
    names = a.only or (["mixed"] + sorted(CASES))  # longest first
    jobs = []
    for name in names:
        n = a.mixed_cases if name == "mixed" else a.cases
        conc = a.concurrency + 2 if name == "mixed" else a.concurrency
        for suffix in ("", "_repro"):
            out = base / f"{name}{suffix}"
            jobs.append((out, [sys.executable, "-m", "sim.run", "--scenario", name, "--cases", str(n),
                               "--seed", str(a.seed), "--concurrency", str(conc), "--think-scale", "0",
                               "--out", str(out)]))
    t0 = time.time()
    if not a.skip_runs:
        pending, running = list(jobs), []
        while pending or running:
            while pending and len(running) < a.parallel:
                out, cmd = pending.pop(0)
                out.mkdir(parents=True, exist_ok=True)
                fh = open(out.with_suffix(".log"), "w", encoding="utf-8")
                running.append((out, subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT), fh))
                print(f"[round] started {out}", flush=True)
            for item in list(running):
                out, proc, fh = item
                if proc.poll() is not None:
                    fh.close()
                    running.remove(item)
                    print(f"[round] finished {out} (exit {proc.returncode}, {time.time() - t0:.0f}s)", flush=True)
            time.sleep(2)
    results = {}
    for name in names:
        run, repro = base / name, base / f"{name}_repro"
        proc = subprocess.run([sys.executable, "-m", "sim.quality", str(run), "--repro", str(repro)],
                              capture_output=True, text=True)
        (base / f"{name}.quality.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        rep = json.loads((run / "quality.json").read_text(encoding="utf-8")) if (run / "quality.json").exists() else {}
        results[name] = {"exit": proc.returncode, "failed": rep.get("failed"), "poor": rep.get("poor"),
                         "counts": {s: d["counts"] for s, d in rep.get("scopes", {}).items()}}
        print(f"[round] quality {name}: exit {proc.returncode}, failed {rep.get('failed')}, poor {rep.get('poor')}")
    (base / "round.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"[round] done in {time.time() - t0:.0f}s -> {base / 'round.json'}")
    sys.exit(1 if any(r["exit"] != 0 for r in results.values()) else 0)


if __name__ == "__main__":
    main()
