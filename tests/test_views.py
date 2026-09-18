"""View induction and hidden-context recovery."""

from tpv.log.demo import hidden_context_log, running_example
from tpv.views.views import assign_view, induce_views


def _rand_index(labels_a, labels_b):
    """Adjusted Rand index between two label assignments over the same items."""
    from tpv.quality.agreement import adjusted_rand_index

    keys = list(labels_a)
    return adjusted_rand_index([labels_a[k] for k in keys], [labels_b[k] for k in keys])


def test_views_partition_the_trace_set():
    log = running_example()
    views = induce_views(log)
    covered = [t for v in views for t in v.traces]
    assert sorted(map(repr, covered)) == sorted(map(repr, log.trace_set()))
    assert sum(v.frequency for v in views) == log.n_cases


def test_hidden_context_recovered_exactly():
    log, ground_truth = hidden_context_log({"admin": 30, "clerk": 30, "auditor": 15})
    views = induce_views(log)
    assert len(views) == 3

    trace_to_view = assign_view(log, views)
    case_to_view = {}
    for trace, count in log.variants.items():
        for cid in log.case_ids[trace]:
            case_to_view[cid] = trace_to_view[trace]

    ari = _rand_index(ground_truth, case_to_view)
    assert ari == 1.0  # the three roles are perfectly separated


def test_running_example_view_identifiers_match_the_paper():
    """C1/C2/C3 of Sect. 4.5, pinned.

    The README's library snippet printed C2 and C3 swapped for a while; this is
    the invariant that catches it.  C2 is the *sequential* view and C3 the
    *restricted* one, matching Sect. 4.5's C_1 = {s1,s2}, C_2 = {s3,s4},
    C_3 = {s5,s6}.
    """
    got = {v.label: v.identifier.canonical_str() for v in induce_views(running_example())}
    assert got == {
        "C1": "seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))",
        "C2": "seq(o, xor(b, c), xor(d, e), f, xor(g, h))",
        "C3": "seq(o, b, d, f, xor(g, h))",
    }


def test_executed_activity_is_always_enabled():
    """Def. 3.1 requires a in E.  Guards every generator against a bad edit."""
    from tpv.log.synth import build_all
    from tpv.log.types import pi_act, pi_en

    for name, log, _gt, _attrs in build_all(quick=True):
        for trace in log.trace_set():
            for i, event in enumerate(trace, start=1):
                assert pi_act(event) in pi_en(event), (name, i, event)


def test_view_labels_and_ordering():
    log, _ = hidden_context_log({"admin": 40, "clerk": 40, "auditor": 20})
    views = induce_views(log)
    assert [v.label for v in views] == ["C1", "C2", "C3"]
    assert views[0].frequency >= views[1].frequency >= views[2].frequency
