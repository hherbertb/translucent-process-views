"""Enrichment from a model's replay states -- tpv/log/enrich.py.

These tests build Petri nets with a known structure, so the enabled sets are
derived from markings rather than written by hand.  That is the whole point of
the module: it produces translucent behaviour that kappa did not design.
"""

import pytest

from tpv.log.enrich import (
    enabled_at_marking,
    enrich_from_model,
    split_and_enrich,
    variants_of,
)
from tpv.log.types import pi_act, pi_en
from tpv.views.views import induce_views

pm4py = pytest.importorskip("pm4py")


def _net(edges, start, end, silent=()):
    """Build an accepting Petri net from ``(place, transition, place)`` triples.

    ``silent`` names transitions that carry no label (taus).
    """
    from pm4py.objects.petri_net.obj import Marking, PetriNet
    from pm4py.objects.petri_net.utils.petri_utils import (
        add_arc_from_to, add_place, add_transition,
    )

    net = PetriNet("test")
    places, transitions = {}, {}

    def place(n):
        if n not in places:
            places[n] = add_place(net, name=n)
        return places[n]

    def trans(n):
        if n not in transitions:
            transitions[n] = add_transition(
                net, name=n, label=None if n in silent else n)
        return transitions[n]

    for src, t, dst in edges:
        add_arc_from_to(place(src), trans(t), net)
        add_arc_from_to(trans(t), place(dst), net)
    im, fm = Marking(), Marking()
    im[place(start)] = 1
    fm[place(end)] = 1
    return net, im, fm


# a -> (b xor c) -> d
_SEQ_CHOICE = [("p0", "a", "p1"), ("p1", "b", "p2"), ("p1", "c", "p2"),
               ("p2", "d", "p3")]


def test_enabled_at_marking_reports_the_choice():
    net, im, fm = _net(_SEQ_CHOICE, "p0", "p3")
    assert enabled_at_marking(net, im) == frozenset({"a"})


def test_enabled_at_marking_looks_through_silent_transitions():
    # a -> tau -> (b xor c):  at the initial marking only `a` is available, but
    # after `a` the tau must be crossed to see that b and c are the real choice
    net, im, fm = _net(
        [("p0", "a", "p1"), ("p1", "t", "p2"), ("p2", "b", "p3"), ("p2", "c", "p3")],
        "p0", "p3", silent={"t"})
    from pm4py.objects.petri_net.semantics import enabled_transitions, execute

    m = im
    (a,) = [t for t in enabled_transitions(net, m) if t.label == "a"]
    m = execute(a, net, m)
    assert enabled_at_marking(net, m) == frozenset({"b", "c"})


def test_enrichment_records_the_choice_and_is_self_consistent():
    net, im, fm = _net(_SEQ_CHOICE, "p0", "p3")
    variants = variants_of({"c1": ["a", "b", "d"], "c2": ["a", "c", "d"]})
    log, report = enrich_from_model(variants, net, im, fm)

    assert report.n_cases_kept == 2 and report.retention == 1.0
    for trace in log.trace_set():
        # Definition 3.1 requires the executed activity to be enabled; with
        # marking-derived sets this holds by construction
        for event in trace:
            assert pi_act(event) in pi_en(event)
        assert pi_en(trace[1]) == frozenset({"b", "c"})  # the choice is visible


def test_non_replayable_traces_are_dropped_and_counted():
    net, im, fm = _net(_SEQ_CHOICE, "p0", "p3")
    variants = variants_of({"c1": ["a", "b", "d"], "c2": ["a", "z", "d"]})
    log, report = enrich_from_model(variants, net, im, fm)
    assert report.n_cases_in == 2
    assert report.n_cases_kept == 1
    assert report.retention == pytest.approx(0.5)


def test_kappa_recovers_two_roles_from_marking_derived_enabled_sets():
    """The end-to-end check: two roles, two models, one merged log, no attribute.

    Role `wide` may choose between b and c; role `narrow` can only do b.  The
    executed sequence <a, b, d> occurs under *both* roles, so nothing in the
    control flow separates them -- only the enabled sets do.  This is the
    hidden-context setting, with the availability information coming from the
    markings of two different nets rather than from a generator.
    """
    wide = _net(_SEQ_CHOICE, "p0", "p3")
    narrow = _net([("p0", "a", "p1"), ("p1", "b", "p2"), ("p2", "d", "p3")],
                  "p0", "p3")
    models = {"wide": wide, "narrow": narrow}

    by_group = {
        "wide": variants_of({"w1": ["a", "b", "d"], "w2": ["a", "c", "d"]}),
        "narrow": variants_of({"n1": ["a", "b", "d"], "n2": ["a", "b", "d"]}),
    }
    # discover() stands in for "mine a model from this group's behaviour"; here
    # it hands back the net that role actually has, so the test isolates the
    # enrichment rather than the miner
    order = iter(["wide", "narrow"])
    log, gt, reports = split_and_enrich(
        by_group, discover=lambda variants: models[next(order)])

    assert all(r.retention == 1.0 for r in reports), [str(r) for r in reports]

    # <a, b, d> is executed under both roles, so classical variants cannot help
    classical = {tuple(a for a, _ in t) for t in log.trace_set()}
    assert ("a", "b", "d") in classical

    views = induce_views(log)
    assert len(views) == 2, [v.identifier.canonical_str() for v in views]

    trace_to_view = {t: v.label for v in views for t in v.traces}
    per_case = {cid: trace_to_view[t]
                for t in log.trace_set() for cid in log.case_ids[t]}
    # every case of a role lands in one view, and the two roles differ
    wide_views = {per_case[c] for c in ("w1", "w2")}
    narrow_views = {per_case[c] for c in ("n1", "n2")}
    assert len(wide_views) == 1 and len(narrow_views) == 1
    assert wide_views != narrow_views


def test_enrichment_works_on_a_real_miner_model_with_silent_transitions():
    """IMf output is full of taus; the enabled set must be read through them.

    Also pins the fact that the fitting-trace filter is lossy: a threshold-0.4
    model does not replay every variant it was mined from, so any evaluation
    built on enriched logs has to report the retention rate rather than assume
    it is 1.0.
    """
    from pm4py.objects.log.obj import Event, EventLog, Trace

    cases = {}
    seqs = [["a", "b", "c", "d"], ["a", "c", "b", "d"], ["a", "b", "d"],
            ["a", "c", "d"], ["a", "b", "c", "b", "c", "d"], ["a", "d"]]
    for i, s in enumerate(seqs * 10):
        cases[f"c{i}"] = s

    el = EventLog()
    for cid, s in cases.items():
        tr = Trace()
        tr.attributes["concept:name"] = cid
        for act in s:
            e = Event()
            e["concept:name"] = act
            tr.append(e)
        el.append(tr)

    net, im, fm = pm4py.discover_petri_net_inductive(el, noise_threshold=0.4)
    assert any(t.label is None for t in net.transitions), "expected silent transitions"

    log, report = enrich_from_model(variants_of(cases), net, im, fm)
    assert report.n_cases_kept > 0
    assert report.retention < 1.0, "the fitting filter is expected to drop traces"
    for trace in log.trace_set():
        for event in trace:
            assert pi_act(event) in pi_en(event)
    # b and c are concurrent in the mined model, so both are enabled at the
    # event that executes either of them -- visible only through the taus
    assert any(pi_en(e) >= frozenset({"b", "c"})
               for t in log.trace_set() for e in t)


# --------------------------------------------------------------------------- #
# Replay must search, not guess.  Two silent transitions lead from p0 to two
# copies of the visible label "x"; only the second copy continues to "y".
# --------------------------------------------------------------------------- #
def _tau_branch_net(reverse=False):
    from pm4py.objects.petri_net.obj import Marking, PetriNet
    from pm4py.objects.petri_net.utils.petri_utils import (
        add_arc_from_to, add_place, add_transition,
    )

    net = PetriNet("tau-branch")
    names = ["p0", "pa", "pb", "pc", "pd", "end"]
    if reverse:
        names = names[::-1]
    P = {n: add_place(net, name=n) for n in names}
    spec = [("t1", None, "p0", "pa"), ("t2", None, "p0", "pb"),
            ("x_dead", "x", "pa", "pc"), ("x_live", "x", "pb", "pd"),
            ("y", "y", "pd", "end")]
    if reverse:
        spec = spec[::-1]
    for name, label, src, dst in spec:
        t = add_transition(net, name=name, label=label)
        add_arc_from_to(P[src], t, net)
        add_arc_from_to(t, P[dst], net)
    im, fm = Marking(), Marking()
    im[P["p0"]] = 1
    fm[P["end"]] = 1
    return net, im, fm


def test_replay_backtracks_out_of_a_silent_dead_end():
    from tpv.log.enrich import _replay_to_translucent

    net, im, fm = _tau_branch_net()
    trace = _replay_to_translucent(net, im, ["x", "y"], fm)
    assert trace is not None, "a replayable trace was dropped"
    assert [a for a, _ in trace] == ["x", "y"]
    assert trace[1][1] == frozenset({"y"})


def test_replay_does_not_depend_on_construction_order():
    from tpv.log.enrich import _replay_to_translucent

    results = {_replay_to_translucent(*_tau_branch_net(reverse=r)[:2], ["x", "y"],
                                      _tau_branch_net(reverse=r)[2])
               for r in (False, True)}
    assert len(results) == 1


def test_replay_requires_the_final_marking():
    from tpv.log.enrich import _replay_to_translucent

    net, im, fm = _tau_branch_net()
    # "x" alone can be replayed, but leaves a token in pc or pd, not in `end`
    assert _replay_to_translucent(net, im, ["x"], fm) is None
    assert _replay_to_translucent(net, im, ["x"]) is not None   # without fm: prefix replay
