"""Synthetic translucent event logs with a known hidden context.

Each ground-truth generator returns ``(TranslucentLog, ground_truth, attrs)``:

* ``ground_truth`` maps every case id to the hidden label (role / configuration)
  that produced it.  The label is *not* stored in the log -- exactly the setting
  of the paper: the view-defining context is only visible indirectly through the
  enabled activities.
* ``attrs`` maps every case id to a dict of recorded *case attributes*: a
  **clean** set that is informative about the hidden label (``role`` bijective
  with it, ``department`` many-to-one, ``location`` 80%-biased, ``seniority`` a
  shifted Gaussian) and a **noisy** set that is independent of it
  (``ticket_channel``, ``client_tier``, ``weekday``, ``noise_score``,
  ``flag_a``/``flag_b``).  The attributes let the trace-clustering baselines
  cluster on recorded context; ``kappa`` uses none of them -- only enabled
  activities.

The generators are designed so that, per hidden view, *many* classical variants
(executed projections) and even more exact translucent variants map to a single
``kappa`` abstraction identifier -- this is what makes classical-variant and
translucent-variant grouping over-separate while ``kappa`` recovers the hidden
context.
"""

from __future__ import annotations

import hashlib
import random
from typing import Callable, Dict, Iterator, List, Tuple

from tpv.log.demo import (
    hidden_context_log,
    loop_process_log,
    perturb_enabled,
)
from tpv.log.tasks import task_mining_helpdesk
from tpv.log.types import TranslucentLog, TranslucentTrace, executed_projection

GroundTruth = Dict[str, str]
Attributes = Dict[str, Dict[str, object]]
LogGTAttrs = Tuple[TranslucentLog, "GroundTruth | None", "Attributes | None"]


def _fs(s) -> frozenset:
    return frozenset(s)


def _pack(entries, name: str, gt, attrs) -> LogGTAttrs:
    return TranslucentLog.from_traces(entries, name=name), gt, attrs


# --------------------------------------------------------------------------- #
# case attributes -- clean (informative) + noisy (uninformative)
# --------------------------------------------------------------------------- #
ATTRIBUTE_SCHEMA: Dict[str, Dict[str, object]] = {
    # ``role`` IS the hidden label, verbatim.  It is deliberately its own kind
    # ("oracle") rather than "clean": clustering on it cannot fail, so a
    # baseline given it is an upper bound on what any method could achieve, not
    # a competitor.  Reporting it as a "clean attribute" overstated the
    # baseline; the clean set below is informative but not identifying.
    "role": dict(kind="oracle", type="categorical",
                 desc="bijective with the hidden view / role label -- an oracle"),
    "department": dict(kind="clean", type="categorical",
                       desc="coarser grouping; several hidden labels share one "
                            "department (many-to-one)"),
    "location": dict(kind="clean", type="categorical",
                     desc="each hidden label has an 80%-dominant site; the "
                          "remaining 20% is drawn uniformly from the other sites"),
    "seniority": dict(kind="clean", type="numeric",
                      desc="Gaussian with a per-label mean shift and unit "
                           "variance -- overlapping, only partially informative"),
    "ticket_channel": dict(kind="noisy", type="categorical",
                           desc="4 levels drawn uniformly, independent of the "
                                "hidden label"),
    "client_tier": dict(kind="noisy", type="categorical",
                        desc="3 levels drawn uniformly, independent of the "
                             "hidden label"),
    "weekday": dict(kind="noisy", type="categorical",
                    desc="7 levels drawn uniformly, independent of the hidden "
                         "label"),
    "noise_score": dict(kind="noisy", type="numeric",
                        desc="standard normal N(0,1), independent of the hidden "
                             "label"),
    "flag_a": dict(kind="noisy", type="categorical",
                   desc="Bernoulli(0.5), independent of the hidden label"),
    "flag_b": dict(kind="noisy", type="categorical",
                   desc="Bernoulli(0.5), independent of the hidden label"),
}

CLEAN_ATTRS = [a for a, m in ATTRIBUTE_SCHEMA.items() if m["kind"] == "clean"]
NOISY_ATTRS = [a for a, m in ATTRIBUTE_SCHEMA.items() if m["kind"] == "noisy"]
ORACLE_ATTRS = [a for a, m in ATTRIBUTE_SCHEMA.items() if m["kind"] == "oracle"]
NUMERIC_ATTRS = {a for a, m in ATTRIBUTE_SCHEMA.items() if m["type"] == "numeric"}

assert "role" in ORACLE_ATTRS and "role" not in CLEAN_ATTRS, (
    "role is the hidden label; it must never be part of the 'clean' feature set"
)

_CHANNELS = ("web", "phone", "email", "chat")
_TIERS = ("bronze", "silver", "gold")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _stable_idx(label: str, n: int) -> int:
    """Deterministic 0..n-1 bucket for a label, independent of the generator."""
    h = hashlib.md5(label.encode("utf-8")).hexdigest()
    return int(h, 16) % n


def make_attributes(hidden_label: str, rnd: random.Random) -> Dict[str, object]:
    """Recorded case attributes for a case produced by ``hidden_label``.

    Clean attributes carry information about the label; noisy attributes do not
    (see :data:`ATTRIBUTE_SCHEMA`).
    """
    home = f"site_{_stable_idx(hidden_label, 4)}"
    return {
        "role": hidden_label,
        "department": f"dept_{_stable_idx(hidden_label, 3)}",
        "location": home if rnd.random() < 0.8 else f"site_{rnd.randrange(4)}",
        "seniority": round(rnd.gauss(2.0 + _stable_idx(hidden_label, 5), 1.0), 2),
        "ticket_channel": rnd.choice(_CHANNELS),
        "client_tier": rnd.choice(_TIERS),
        "weekday": rnd.choice(_WEEKDAYS),
        "noise_score": round(rnd.gauss(0.0, 1.0), 3),
        "flag_a": rnd.choice(("y", "n")),
        "flag_b": rnd.choice(("y", "n")),
    }


# --------------------------------------------------------------------------- #
# shared control-flow helper: one "choice group" of binary choices, either
# resolved concurrently (interleaved, wide enabled sets) or in sequence
# --------------------------------------------------------------------------- #
def _choice_group(
    pairs: List[str], parallel: bool, rnd: random.Random
) -> List[Tuple[str, frozenset]]:
    """Events for a group of binary choices ``pairs`` (e.g. ``["bc", "de"]``).

    ``parallel``: the choices are concurrent -- picked in a random order, each
    event enabling every activity of every still-unresolved pair.  Otherwise the
    choices are resolved left to right, each event enabling only its own pair.
    """
    chosen = {p: rnd.choice(p) for p in pairs}
    if not parallel:
        return [(chosen[p], _fs(p)) for p in pairs]
    order = list(pairs)
    rnd.shuffle(order)
    pending = list(pairs)
    out: List[Tuple[str, frozenset]] = []
    for p in order:
        out.append((chosen[p], _fs("".join(pending))))
        pending.remove(p)
    return out


# --------------------------------------------------------------------------- #
# 1. running example -- L_run of Section 3 / 4.6, at log scale
# --------------------------------------------------------------------------- #
# The six-trace L_run lives in tpv.log.demo.running_example(); this is the same
# process sampled to many cases.  Eight activities: o = open a request; {b,c} =
# alternative checks; {d,e} = alternative assessments; f = submit; {g,h} =
# approve or reject.  The hidden label decides how the two choices are offered
# and yields exactly the three process views of Section 4.6:
#     C1 (independent): seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))
#     C2 (sequential) : seq(o, xor(b, c), xor(d, e), f, xor(g, h))
#     C3 (restricted) : seq(o, b, d, f, xor(g, h))
_RE_ACT = _fs("obcdefgh")
# Order is load-bearing: with balanced classes induce_views breaks the frequency
# tie by first appearance, so emitting the concurrent view first is what pins the
# induced labels to C1 / C2 / C3.  (independent -> C1, sequential -> C2,
# restricted -> C3.)  The label *strings* are also kept as-is (not renamed to
# parallel/sequential/pinned) because make_attributes buckets department /
# location by md5 of the label, and renaming collapses all three into one bucket.
_RE_VIEWS = ("independent", "sequential", "restricted")


def _re_trace(view: str, rnd: random.Random) -> TranslucentTrace:
    if view == "independent":       # the two choices are concurrent
        mid = _choice_group(["bc", "de"], True, rnd)
    elif view == "sequential":      # the same choices, left to right
        mid = _choice_group(["bc", "de"], False, rnd)
    else:                           # restricted -- each choice pinned to one branch
        mid = _choice_group(["b", "d"], False, rnd)
    gh = rnd.choice("gh")
    return tuple([("o", _fs("o"))] + mid + [("f", _fs("f")), (gh, _fs("gh"))])


def running_example_log(
    n_cases: int = 1500, seed: int = 1, noise: float = 0.0
) -> LogGTAttrs:
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    gt: GroundTruth = {}
    attrs: Attributes = {}
    for i in range(n_cases):
        view = _RE_VIEWS[i % len(_RE_VIEWS)]
        trace = perturb_enabled(_re_trace(view, rnd), rnd, noise, _RE_ACT)
        cid = f"c{i}"
        entries.append((trace, cid))
        gt[cid] = view
        attrs[cid] = make_attributes(view, rnd)
    # deliberately NOT shuffled: the three views tie at n/3 cases each, and
    # induce_views resolves the tie by first appearance -- keeping the concurrent
    # view first is what makes the induced identifiers line up with C1..C3.
    return _pack(entries, "running_example", gt, attrs)


# --------------------------------------------------------------------------- #
# 2. k hidden configurations over one base process -- varies the ground-truth k
# --------------------------------------------------------------------------- #
# a = start; {p,q} {r,s} {u,v} = three binary choices; m = extra step; z = end.
_KV_ACT = _fs("apqrsuvmz")
_KV_CONFIGS = ("parallel", "sequential", "restricted", "skip", "extra")
_KV_CS = {**dict.fromkeys("pq", "pq"),
          **dict.fromkeys("rs", "rs"),
          **dict.fromkeys("uv", "uv")}


def _kv_trace(cfg: str, rnd: random.Random) -> TranslucentTrace:
    pq = rnd.choice("pq")
    rs = rnd.choice("rs")
    uv = rnd.choice("uv")
    if cfg == "parallel":          # and(xor(p,q), xor(r,s), xor(u,v))
        picks = [pq, rs, uv]
        rnd.shuffle(picks)
        pending = ["pq", "rs", "uv"]
        mid: List[Tuple[str, frozenset]] = []
        for act in picks:
            mid.append((act, _fs("".join(pending))))
            pending.remove(_KV_CS[act])
        ev = [("a", _fs("a"))] + mid + [("z", _fs("z"))]
    elif cfg == "sequential":
        ev = [("a", _fs("a")), (pq, _fs("pq")), (rs, _fs("rs")), (uv, _fs("uv")),
              ("z", _fs("z"))]
    elif cfg == "restricted":
        ev = [("a", _fs("a")), ("p", _fs("p")), ("r", _fs("r")), ("u", _fs("u")),
              ("z", _fs("z"))]
    elif cfg == "skip":
        ev = [("a", _fs("az")), ("z", _fs("z"))]
    else:                          # extra -- sequential choices plus a step m
        ev = [("a", _fs("a")), (pq, _fs("pq")), (rs, _fs("rs")), (uv, _fs("uv")),
              ("m", _fs("m")), ("z", _fs("z"))]
    return tuple(ev)


def k_view_log(
    k: int = 4, n_per_view: int = 180, seed: int = 1, noise: float = 0.0
) -> LogGTAttrs:
    if not 2 <= k <= 5:
        raise ValueError("k must be in 2..5")
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    gt: GroundTruth = {}
    attrs: Attributes = {}
    idx = 0
    for cfg in _KV_CONFIGS[:k]:
        for _ in range(n_per_view):
            trace = perturb_enabled(_kv_trace(cfg, rnd), rnd, noise, _KV_ACT)
            cid = f"c{idx}"
            idx += 1
            entries.append((trace, cid))
            gt[cid] = cfg
            attrs[cid] = make_attributes(cfg, rnd)
    rnd.shuffle(entries)
    return _pack(entries, f"k_view_k{k}", gt, attrs)


# --------------------------------------------------------------------------- #
# 3. partial parallelism -- hidden views differ in which pairs are concurrent
# --------------------------------------------------------------------------- #
_PP_ACT = _fs("obcdeijlmfghk")
_PP_VIEWS = ("bc_de_par", "de_ij_par", "ij_lm_par", "all_par", "all_seq")


def _pp_trace(view: str, rnd: random.Random) -> TranslucentTrace:
    if view == "bc_de_par":
        mid = (_choice_group(["bc", "de"], True, rnd)
               + _choice_group(["ij"], False, rnd)
               + _choice_group(["lm"], False, rnd))
    elif view == "de_ij_par":
        mid = (_choice_group(["bc"], False, rnd)
               + _choice_group(["de", "ij"], True, rnd)
               + _choice_group(["lm"], False, rnd))
    elif view == "ij_lm_par":
        mid = (_choice_group(["bc"], False, rnd)
               + _choice_group(["de"], False, rnd)
               + _choice_group(["ij", "lm"], True, rnd))
    elif view == "all_par":
        mid = _choice_group(["bc", "de", "ij", "lm"], True, rnd)
    else:                          # all_seq
        mid = _choice_group(["bc", "de", "ij", "lm"], False, rnd)
    gh = rnd.choice("gh")
    tail = [("f", _fs("f")), (gh, _fs("gh")), ("k", _fs("k"))]
    return tuple([("o", _fs("o"))] + mid + tail)


def partial_parallel_log(
    n_cases: int = 800, seed: int = 1, noise: float = 0.0
) -> LogGTAttrs:
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    gt: GroundTruth = {}
    attrs: Attributes = {}
    for i in range(n_cases):
        view = _PP_VIEWS[i % len(_PP_VIEWS)]
        trace = perturb_enabled(_pp_trace(view, rnd), rnd, noise, _PP_ACT)
        cid = f"c{i}"
        entries.append((trace, cid))
        gt[cid] = view
        attrs[cid] = make_attributes(view, rnd)
    rnd.shuffle(entries)
    return _pack(entries, "partial_parallel", gt, attrs)


# --------------------------------------------------------------------------- #
# 4. enterprise -- ~20 activities, 5 hidden roles, three review blocks that are
#    each parallel or sequential depending on the role, plus an optional
#    documentation step
# --------------------------------------------------------------------------- #
_ENT_ACT = _fs("szbcdeghijklmnxypqruw")
_ENT_CONFIGS = ("ops", "triage", "review", "audit", "legal")
# (block1 parallel, block2 parallel, block3 parallel, documentation present)
_ENT_MODES = {
    "ops":    (True,  True,  True,  True),
    "triage": (False, True,  True,  True),
    "review": (True,  False, True,  True),
    "audit":  (True,  True,  False, True),
    "legal":  (False, False, False, False),
}


def _ent_trace(cfg: str, rnd: random.Random) -> TranslucentTrace:
    b1, b2, b3, docs = _ENT_MODES[cfg]
    ev: List[Tuple[str, frozenset]] = [("s", _fs("s")), ("z", _fs("z"))]
    ev += _choice_group(["bc", "de"], b1, rnd)
    ev += _choice_group(["gh", "ij"], b2, rnd)
    ev += _choice_group(["kl", "mn", "xy"], b3, rnd)
    if docs:
        ev.append(("p", _fs("p")))
    ev.append((rnd.choice("qru"), _fs("qru")))
    ev.append(("w", _fs("w")))
    return tuple(ev)


def enterprise_log(
    n_cases: int = 3000, n_views: int = 5, seed: int = 1, noise: float = 0.0
) -> LogGTAttrs:
    if not 3 <= n_views <= 5:
        raise ValueError("n_views must be in 3..5")
    cfgs = _ENT_CONFIGS[:n_views]
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    gt: GroundTruth = {}
    attrs: Attributes = {}
    for i in range(n_cases):
        cfg = cfgs[i % len(cfgs)]
        trace = perturb_enabled(_ent_trace(cfg, rnd), rnd, noise, _ENT_ACT)
        cid = f"c{i}"
        entries.append((trace, cid))
        gt[cid] = cfg
        attrs[cid] = make_attributes(cfg, rnd)
    rnd.shuffle(entries)
    return _pack(entries, "enterprise", gt, attrs)


# --------------------------------------------------------------------------- #
# 5. wrappers around the existing demo generators
# --------------------------------------------------------------------------- #
def hidden_context_gt(cases_per_role=None, seed: int = 1, noise: float = 0.0) -> LogGTAttrs:
    log, gt = hidden_context_log(cases_per_role, seed=seed, noise=noise)
    arnd = random.Random(seed + 991)
    attrs = {cid: make_attributes(role, arnd) for cid, role in gt.items()}
    return log, gt, attrs


def helpdesk_gt(n_agent: int = 200, n_supervisor: int = 150, seed: int = 1,
                noise: float = 0.0, rework: bool = False) -> LogGTAttrs:
    log, gt = task_mining_helpdesk(n_agent, n_supervisor, seed=seed, noise=noise,
                                   rework=rework)
    arnd = random.Random(seed + 991)
    attrs = {cid: make_attributes(role, arnd) for cid, role in gt.items()}
    return log, gt, attrs


def loop_process_gt(n_cases: int = 400, seed: int = 1, noise: float = 0.0) -> LogGTAttrs:
    """A rework loop -- no clean hidden context (kappa over-segments loops).

    Returned with ground truth ``None`` so it contributes only to the
    model-quality experiment, where it honestly shows the loop limitation.
    """
    log = loop_process_log(n_cases, seed=seed, noise=noise)
    return log, None, None


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
Spec = Dict[str, object]

LOG_SPECS: List[Spec] = [
    dict(name="running_example", fn=running_example_log,
         quick=dict(n_cases=120), full=dict(n_cases=1500)),
    dict(name="running_example_big", fn=running_example_log,
         quick=dict(n_cases=120, seed=2), full=dict(n_cases=4000, seed=2)),
    dict(name="k_view_k2", fn=k_view_log,
         quick=dict(k=2, n_per_view=45), full=dict(k=2, n_per_view=400)),
    dict(name="k_view_k3", fn=k_view_log,
         quick=dict(k=3, n_per_view=35), full=dict(k=3, n_per_view=400)),
    dict(name="k_view_k4", fn=k_view_log,
         quick=dict(k=4, n_per_view=30), full=dict(k=4, n_per_view=400)),
    dict(name="k_view_k5", fn=k_view_log,
         quick=dict(k=5, n_per_view=24), full=dict(k=5, n_per_view=360)),
    dict(name="partial_parallel", fn=partial_parallel_log,
         quick=dict(n_cases=120), full=dict(n_cases=2000)),
    dict(name="enterprise", fn=enterprise_log,
         quick=dict(n_cases=150), full=dict(n_cases=3000)),
    dict(name="enterprise_xl", fn=enterprise_log,
         quick=dict(n_cases=90, seed=3), full=dict(n_cases=4000, seed=3)),
    dict(name="hidden_context", fn=hidden_context_gt,
         quick=dict(cases_per_role={"admin": 24, "clerk": 24, "auditor": 12}),
         full=dict(cases_per_role={"admin": 420, "clerk": 420, "auditor": 200})),
    dict(name="task_mining_helpdesk", fn=helpdesk_gt,
         quick=dict(n_agent=26, n_supervisor=18),
         full=dict(n_agent=320, n_supervisor=230)),
    dict(name="loop_process", fn=loop_process_gt,
         quick=dict(n_cases=60), full=dict(n_cases=600)),
]


def build_all(
    quick: bool = False, seed: "int | None" = None
) -> Iterator[Tuple[str, TranslucentLog, "GroundTruth | None", "Attributes | None"]]:
    key = "quick" if quick else "full"
    for spec in LOG_SPECS:
        fn: Callable[..., LogGTAttrs] = spec["fn"]  # type: ignore[assignment]
        kwargs = dict(spec[key])  # type: ignore[arg-type]
        if seed is not None:
            kwargs["seed"] = int(kwargs.get("seed", 1)) + seed
        out = fn(**kwargs)
        if len(out) == 2:  # pragma: no cover - defensive
            log, gt = out  # type: ignore[misc]
            attrs = None
        else:
            log, gt, attrs = out
        yield spec["name"], log, gt, attrs  # type: ignore[misc]


__all__ = [
    "running_example_log",
    "k_view_log",
    "partial_parallel_log",
    "enterprise_log",
    "hidden_context_gt",
    "helpdesk_gt",
    "loop_process_gt",
    "make_attributes",
    "ATTRIBUTE_SCHEMA",
    "CLEAN_ATTRS",
    "NOISY_ATTRS",
    "NUMERIC_ATTRS",
    "LOG_SPECS",
    "build_all",
]
