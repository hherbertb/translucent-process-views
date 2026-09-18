"""Pin Python's string-hash seed for every experiment run.

Python randomises ``hash(str)`` per process, so any code that iterates a set of
strings sees a different order in every run.  Seeding the RNGs does not help.
Two places in the pipeline depended on that order: pm4py's inductive miner
(on the road-traffic log it mined structurally different nets for the same
sub-log in different processes) and, before it was fixed, the service-desk
generator.  The semi-real results in the first submission draft could not be
reproduced for that reason.

The seed can only be set before the interpreter starts, so the runner re-launches
itself once with ``PYTHONHASHSEED=0`` when it is not already set to that value.
"""
from __future__ import annotations

import os
import subprocess
import sys

HASH_SEED = "0"


def pin_hash_seed() -> None:
    """Re-run the current command under ``PYTHONHASHSEED=0`` unless it already is."""
    if os.environ.get("PYTHONHASHSEED") == HASH_SEED:
        return
    env = dict(os.environ, PYTHONHASHSEED=HASH_SEED)
    print(f"[repro] re-launching with PYTHONHASHSEED={HASH_SEED}", file=sys.stderr, flush=True)
    raise SystemExit(subprocess.call([sys.executable, *sys.argv], env=env))
