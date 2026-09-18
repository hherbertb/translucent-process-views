"""Demo translucent event logs.

* :func:`running_example` -- the exact log ``L_run`` of Section 4.1 / 4.6.
* :func:`hidden_context_log` -- a synthetic log whose cases come from several
  hidden "views" (roles) that classical discovery would merge into one model;
  the role attribute is dropped so that :func:`tpv.views.induce_views` has to
  recover the grouping from enabled-activity information alone.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from tpv.log.types import TranslucentLog, TranslucentTrace

# activity meanings for the running example (Section 4.1):
# o = open request; b, c = alternative checks; d, e = alternative assessments;
# f = submit request; g, h = approve or reject.
_E = frozenset


def running_example() -> TranslucentLog:
    """``L_run = [sigma_1, ..., sigma_6]`` -- Section 4.1.

    Yields exactly the three process views of Section 4.6::

        C1 = {s1, s2}: seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))
        C2 = {s3, s4}: seq(o, xor(b, c), xor(d, e), f, xor(g, h))
        C3 = {s5, s6}: seq(o, b, d, f, xor(g, h))
    """
    s1 = ((("o", _E("o")), ("b", _E("bcde")), ("d", _E("de")), ("f", _E("f")), ("g", _E("gh"))))
    s2 = ((("o", _E("o")), ("c", _E("bcde")), ("e", _E("de")), ("f", _E("f")), ("h", _E("gh"))))
    s3 = ((("o", _E("o")), ("b", _E("bc")), ("d", _E("de")), ("f", _E("f")), ("g", _E("gh"))))
    s4 = ((("o", _E("o")), ("c", _E("bc")), ("e", _E("de")), ("f", _E("f")), ("h", _E("gh"))))
    s5 = ((("o", _E("o")), ("b", _E("b")), ("d", _E("d")), ("f", _E("f")), ("g", _E("gh"))))
    s6 = ((("o", _E("o")), ("b", _E("b")), ("d", _E("d")), ("f", _E("f")), ("h", _E("gh"))))
    return TranslucentLog.from_traces(
        [(t, f"case-{i}") for i, t in enumerate([s1, s2, s3, s4, s5, s6], start=1)],
        name="running-example",
    )


# -- hidden-context synthetic log -----------------------------------------------
# Three roles handle the same request-like process but see different structure.
#   a = login   b, c = two preparation steps   d = review
#   e = approve  f = reject   g = logout
_ROLE_TEMPLATES = {
    # admin sees b and c as concurrent
    "admin": "parallel_bc",
    # clerk executes b then c strictly sequentially
    "clerk": "sequential_bc",
    # auditor never touches b or c
    "auditor": "skip_bc",
}


def _decision(rnd: random.Random) -> Tuple[str, frozenset]:
    """Final xor(e, f) block."""
    chosen = rnd.choice(["e", "f"])
    return chosen, _E("ef")


def _trace_admin(rnd: random.Random) -> TranslucentTrace:
    dec, dec_en = _decision(rnd)
    if rnd.random() < 0.5:
        prep = [("b", _E("bc")), ("c", _E("c"))]
    else:
        prep = [("c", _E("bc")), ("b", _E("b"))]
    return tuple(
        [("a", _E("a"))]
        + prep
        + [("d", _E("d")), (dec, dec_en), ("g", _E("g"))]
    )


def _trace_clerk(rnd: random.Random) -> TranslucentTrace:
    dec, dec_en = _decision(rnd)
    return (
        ("a", _E("a")),
        ("b", _E("b")),
        ("c", _E("c")),
        ("d", _E("d")),
        (dec, dec_en),
        ("g", _E("g")),
    )


def _trace_auditor(rnd: random.Random) -> TranslucentTrace:
    dec, dec_en = _decision(rnd)
    return (
        ("a", _E("a")),
        ("d", _E("d")),
        (dec, dec_en),
        ("g", _E("g")),
    )


_GENERATORS = {
    "admin": _trace_admin,
    "clerk": _trace_clerk,
    "auditor": _trace_auditor,
}


# Mix of add-vs-drop corruption per noise mode.
#
# "balanced" is the symmetric coin flip.  "activitygen" is skewed towards
# spurious additions, matching what extracting enabled activities from
# screenshots actually does: ActivityGen [Beyel, Manuel & van der Aalst, ECAI
# 2024, Tab. 3] reports GUI-element detection on RICO at IoU > 0.9 with
# precision 0.233 and recall 0.567 -- i.e. far more false positives (an element
# detected that is not really an available action) than misses.  p_add is set
# from that precision/recall ratio: FP/(FP+FN) with the reported values is
# ~0.79.
_NOISE_MODES = {"balanced": 0.5, "activitygen": 0.79}


def perturb_enabled(
    trace: TranslucentTrace,
    rnd: random.Random,
    noise: float,
    universe: "frozenset[str] | set[str]",
    mode: str = "balanced",
) -> TranslucentTrace:
    """Corrupt one enabled activity per event with probability ``noise``.

    Exactly one activity is added or dropped whenever the coin comes up, so the
    realised corruption rate equals ``noise``: an addition is drawn from
    ``universe - enabled`` (never a no-op re-add) and a drop is only attempted
    when there is a non-executed activity to remove -- if there is not, an
    addition is made instead.  The executed activity is never dropped, since
    Def. 3.1 requires it to be enabled.

    ``mode`` selects the add/drop mix; see :data:`_NOISE_MODES`.  Shared by
    every synthetic generator so that "noise" means the same thing across logs.
    """
    if noise <= 0:
        return trace
    try:
        p_add = _NOISE_MODES[mode]
    except KeyError:
        raise ValueError(
            f"unknown noise mode {mode!r}; expected one of {sorted(_NOISE_MODES)}"
        ) from None
    pool = frozenset(universe)
    out = []
    for act, enabled in trace:
        enabled = set(enabled)
        if rnd.random() < noise:
            droppable = sorted(enabled - {act})
            addable = sorted(pool - enabled)
            # fall back to whichever operation is actually available, so the
            # realised rate does not silently fall below `noise`
            do_add = rnd.random() < p_add
            if (do_add and addable) or not droppable:
                if addable:
                    enabled.add(rnd.choice(addable))
            elif droppable:
                enabled.discard(rnd.choice(droppable))
        out.append((act, frozenset(enabled)))
    return tuple(out)


def realised_noise_rate(
    clean: TranslucentTrace, noisy: TranslucentTrace
) -> "tuple[int, int]":
    """``(corrupted_events, total_events)`` between a trace and its noisy copy.

    Lets the evaluation report the corruption rate it actually applied instead
    of the rate it asked for.
    """
    assert len(clean) == len(noisy)
    changed = sum(1 for (_, a), (_, b) in zip(clean, noisy) if a != b)
    return changed, len(clean)


def _perturb(trace: TranslucentTrace, rnd: random.Random, noise: float) -> TranslucentTrace:
    return perturb_enabled(trace, rnd, noise, {"a", "b", "c", "d", "e", "f", "g"})


def hidden_context_log(
    cases_per_role: Dict[str, int] | None = None,
    seed: int = 42,
    shuffle: bool = True,
    noise: float = 0.0,
) -> Tuple[TranslucentLog, Dict[str, str]]:
    """Build a synthetic log with hidden roles.

    Returns the merged translucent log (role attribute dropped) and a
    ``case_id -> role`` ground-truth map for evaluation.  ``noise`` perturbs the
    enabled sets so that ``kappa`` recovery degrades.
    """
    cases_per_role = cases_per_role or {"admin": 40, "clerk": 40, "auditor": 20}
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    ground_truth: Dict[str, str] = {}
    cid = 0
    for role, n in cases_per_role.items():
        gen = _GENERATORS[role]
        for _ in range(n):
            case_id = f"case-{cid}"
            entries.append((_perturb(gen(rnd), rnd, noise), case_id))
            ground_truth[case_id] = role
            cid += 1
    if shuffle:
        rnd.shuffle(entries)
    log = TranslucentLog.from_traces(entries, name="hidden-context")
    return log, ground_truth


# -- process with a genuine executed loop --------------------------------------
# A claims process with a rework loop:
#   register -> assess -> (request_docs -> assess)* -> decide -> archive
# From an `assess` the analyst may loop (request_docs) or move on (decide), so
# `assess` has {assess, request_docs, decide} enabled; this yields a real loop in
# the discovered model and repeated activities in the executed trace.
_LOOP_UNIVERSE = frozenset({"register", "assess", "request_docs", "decide", "archive"})


def loop_process_log(
    n_cases: int = 120,
    seed: int = 13,
    noise: float = 0.0,
    max_rework: int = 3,
) -> TranslucentLog:
    """Synthetic single-context log containing a real executed rework loop."""
    rnd = random.Random(seed)
    triage = frozenset({"assess", "request_docs", "decide"})
    entries: List[Tuple[TranslucentTrace, str]] = []
    for cid in range(n_cases):
        # geometric-ish rework count
        k = 0
        while k < max_rework and rnd.random() < 0.35:
            k += 1
        events: List[Tuple[str, frozenset]] = [("register", frozenset({"register"}))]
        events.append(("assess", triage))
        for _ in range(k):
            events.append(("request_docs", triage))
            events.append(("assess", triage))
        events.append(("decide", frozenset({"decide", "archive"})))
        events.append(("archive", frozenset({"archive"})))
        trace = perturb_enabled(tuple(events), rnd, noise, _LOOP_UNIVERSE)
        entries.append((trace, f"case-{cid}"))
    return TranslucentLog.from_traces(entries, name="loop-process")


__all__ = [
    "running_example",
    "hidden_context_log",
    "loop_process_log",
    "perturb_enabled",
]
