"""Coarser members of the kappa family, and a support filter, on noisy and real logs.

kappa never mixes hidden groups -- purity is 1.00 on both real logs and stays high
under noise -- it only splits them too finely.  Two ways to coarsen, both staying
inside the paper's framework (Def. 3.2 admits any abstraction function):

  kappa          the identifier of Def. 4.10 (order, repetition and structure)
  kappa-multiset the multiset of local choice sets: forgets the order of blocks
  kappa-set      the set of local choice sets: also forgets repetition, so a loop
                 iterated twice and three times collapse onto one view
  kappa-acts     the set of activities that ever appear in a choice: the coarsest
                 "what was available at all" abstraction

and, orthogonally, a relative-support filter: keep the views holding at least
`theta` of the cases and attach the rest to the kept view whose availability
profile they match best (`nearest`) or leave them alone (`solo`).

Reports ARI plus homogeneity and completeness, because those two say precisely
what kappa gets right (never mixing) and what it gets wrong (splitting).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from sklearn.metrics import (adjusted_rand_score,
                             homogeneity_completeness_v_measure)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# local blocks, straight from Defs. 4.2-4.4 (same code as verify_independent.py)
# --------------------------------------------------------------------------- #
def choice_sets(sigma):
    n = len(sigma)
    act = [e[0] for e in sigma]
    en = [frozenset(e[1]) for e in sigma]
    nxt = [en[i + 1] if i < n - 1 else frozenset() for i in range(n)]
    return [frozenset({act[i]}) | (en[i] - nxt[i]) for i in range(n)]


def key_kappa(sigma):
    from tpv.views.abstraction import kappa
    return kappa(sigma).canonical_str()


def key_multiset(sigma):
    return tuple(sorted(tuple(sorted(c)) for c in choice_sets(sigma)))


def key_set(sigma):
    return frozenset(frozenset(c) for c in choice_sets(sigma))


def key_acts(sigma):
    return frozenset().union(*choice_sets(sigma)) if sigma else frozenset()


ABSTRACTIONS = {"kappa": key_kappa, "kappa-multiset": key_multiset,
                "kappa-set": key_set, "kappa-acts": key_acts}


def profile(sigma) -> Counter:
    """Availability profile: how often each activity was enabled."""
    c: Counter = Counter()
    for _, en in sigma:
        c.update(en)
    return c


def cosine(a: Counter, b: Counter) -> float:
    inter = sum(a[k] * b[k] for k in a if k in b)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return inter / (na * nb) if na and nb else 0.0


def score(log, gt, keyfn, theta=0.0, fallback="solo") -> dict:
    groups: dict = {}
    for t in log.trace_set():
        groups.setdefault(keyfn(t), []).append(t)
    size = {k: sum(len(log.case_ids[t]) for t in ts) for k, ts in groups.items()}
    n = sum(size.values())
    keep = {k for k, s in size.items() if s >= theta * n} if theta > 0 else set(groups)
    if not keep:                                  # theta too large: keep the largest
        keep = {max(size, key=size.get)}

    prof = {k: sum((profile(t) for t in groups[k]), Counter()) for k in keep}
    assign = {}
    for k, ts in groups.items():
        if k in keep:
            for t in ts:
                assign[t] = k
            continue
        for t in ts:
            if fallback == "nearest":
                assign[t] = max(prof, key=lambda kk: cosine(profile(t), prof[kk]))
            else:
                assign[t] = f"solo::{hash(t)}"
    pred, true = [], []
    for t, k in assign.items():
        for cid in log.case_ids[t]:
            pred.append(str(k))
            true.append(gt[str(cid)] if str(cid) in gt else gt[cid])
    h, c, _ = homogeneity_completeness_v_measure(
        [str(x) for x in true], pred)
    return {"groups": len(set(pred)), "kept": len(keep),
            "ari": round(adjusted_rand_score([str(x) for x in true], pred), 4),
            "homogeneity": round(h, 4), "completeness": round(c, 4)}


def rows_for(name, log, gt) -> list:
    """Every abstraction on its own, and each with the support filter folded in."""
    out = []
    for aname, fn in ABSTRACTIONS.items():
        for theta, fb in ((0.0, "-"), (0.01, "nearest"), (0.02, "nearest")):
            r = score(log, gt, fn, theta=theta, fallback=("solo" if fb == "-" else fb))
            r.update(log=name, abstraction=aname, theta=theta, fallback=fb)
            out.append(r)
    return out


def synthetic_rows(noises) -> list:
    from tpv.log.tasks import task_mining_servicedesk
    out = []
    for p in noises:
        log, gt, _ = task_mining_servicedesk(250, seed=1, noise=p, noise_mode="balanced")
        for r in rows_for(f"servicedesk p={p}", log, gt):
            out.append(r)
        print(f"  done p={p}", flush=True)
    return out


def real_rows(which) -> list:
    import evaluation.run_semireal as SR
    from tpv.log.enrich import split_and_enrich, variants_of
    spec = SR.SEMIREAL_LOGS[which]
    path = Path(r"C:/Users/beyel/Documents/Code/cabumm/data") / spec["xes"]
    cases, groups = SR.load_xes(path, spec["attribute"], spec.get("top_groups", 4))
    labels = sorted(set(groups.values()))
    by_group = {g: variants_of({c: s for c, s in cases.items() if groups[c] == g})
                for g in labels}
    models = {g: SR.mine(v) for g, v in by_group.items()}
    log, gt, _ = split_and_enrich(by_group,
                                  discover=lambda v, _g=iter(labels): models[next(_g)])
    return rows_for(which, log, gt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", nargs="*", default=[])
    ap.add_argument("--noise", nargs="*", type=float, default=[0.0, 0.05, 0.1, 0.2])
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "results"))
    a = ap.parse_args()
    rows = []
    if a.noise:
        rows += synthetic_rows(a.noise)
    for w in a.real:
        rows += real_rows(w)
    df = pd.DataFrame(rows)[["log", "abstraction", "theta", "fallback", "groups",
                             "kept", "ari", "homogeneity", "completeness"]]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = "_".join(a.real) if a.real else "synthetic"
    df.to_csv(out / f"c1_coarsening_{tag}.csv", index=False)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    from evaluation._repro import pin_hash_seed
    pin_hash_seed()
    raise SystemExit(main())
