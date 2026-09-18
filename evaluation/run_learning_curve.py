"""How many cases does each approach need before its models are good?

BPM 2024 argued that translucent information lets the Inductive Miner discover
good models from fewer traces.  The analogue for process views: a view is
behaviourally homogeneous, so a model discovered per view should saturate at a
smaller number of cases than one global model needs -- even though kappa first
has to *see* a view before it can model it.

Both halves are measured here, on held-out cases, which is what makes this a
sample-efficiency claim rather than a fit claim:

  coverage   share of held-out cases whose key (kappa identifier, classical
             variant, or "everything" for the global model) was seen in training
             and therefore has a model at all
  quality    translucent fitness / precision of the model responsible for a
             held-out case, averaged over covered cases

Reading the two together matters: kappa can look good on quality only because it
answers for the cases it recognises, so a curve without coverage would flatter it.

    venv/Scripts/python evaluation/run_learning_curve.py --log enterprise
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpv.discovery.api import discover_petri_net  # noqa: E402
from tpv.log.synth import build_all  # noqa: E402
from tpv.log.types import TranslucentLog, executed_projection  # noqa: E402
from tpv.quality.metrics import model_quality  # noqa: E402
from tpv.views.abstraction import kappa  # noqa: E402

#: cap the cases scored per key, so the curve is not dominated by alignment cost
SCORE_CAP = 120


def key_of(method: str):
    if method == "kappa":
        return lambda t: kappa(t).canonical_str()
    if method == "classical_variants":
        return lambda t: str(executed_projection(t))
    return lambda t: "all"


def build(cases) -> TranslucentLog:
    return TranslucentLog.from_traces([(t, cid) for cid, t in cases])


def evaluate(method: str, train, test) -> dict:
    kf = key_of(method)
    by_key: dict = {}
    for cid, t in train:
        by_key.setdefault(kf(t), []).append((cid, t))

    models = {}
    for k, items in by_key.items():
        try:
            models[k] = discover_petri_net(build(items), variant="IMtf")
        except BaseException:
            continue

    held: dict = {}
    for cid, t in test:
        held.setdefault(kf(t), []).append((cid, t))

    covered = 0
    acc = {"translucent_fitness": 0.0, "translucent_precision": 0.0, "precision": 0.0}
    for k, items in held.items():
        if k not in models:
            continue
        net, im, fm = models[k]
        sub = build(items[:SCORE_CAP])
        try:
            q = model_quality(sub, net, im, fm, translucent=True)
        except BaseException:
            continue
        n = len(items)
        covered += n
        acc["translucent_fitness"] += (q.translucent_fitness or 0.0) * n
        acc["translucent_precision"] += (q.translucent_precision or 0.0) * n
        acc["precision"] += q.precision * n
    out = {k: (v / covered if covered else float("nan")) for k, v in acc.items()}
    tf, tp = out["translucent_fitness"], out["translucent_precision"]
    out["translucent_f1"] = (2 * tf * tp / (tf + tp)) if (tf and tp) else float("nan")
    out["coverage"] = covered / max(1, len(test))
    out["n_models"] = len(models)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="enterprise")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "results"))
    a = ap.parse_args()

    entry = next((x for x in build_all(False, seed=a.seed) if x[0] == a.log), None)
    if entry is None:
        print(f"unknown log {a.log}", file=sys.stderr)
        return 1
    _, log, _gt, _attrs = entry
    cases = [(cid, t) for t, ids in log.case_ids.items() for cid in ids]
    random.Random(a.seed).shuffle(cases)
    cut = int(0.7 * len(cases))
    train_all, test = cases[:cut], cases[cut:]
    print(f"{a.log}: {len(cases)} cases -> {len(train_all)} train / {len(test)} test", flush=True)

    sizes = [n for n in (50, 100, 200, 400, 800, 1600, 3200) if n <= len(train_all)]
    if sizes[-1] != len(train_all):
        sizes.append(len(train_all))
    rows = []
    for n in sizes:
        for method in ("global", "kappa", "classical_variants"):
            r = evaluate(method, train_all[:n], test)
            r.update(log=a.log, seed=a.seed, n_train=n, method=method)
            rows.append(r)
            print(f"  n={n:5d} {method:20s} coverage {r['coverage']:.2f}  "
                  f"tr.F1 {r['translucent_f1']:.3f}  models {r['n_models']}", flush=True)
    df = pd.DataFrame(rows)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / f"lc_{a.log}.csv", index=False)
    print(f"wrote {out / f'lc_{a.log}.csv'}")
    return 0


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()
    raise SystemExit(main())
