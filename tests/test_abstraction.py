"""The running example of the paper must reproduce Sections 4.3-4.6 exactly."""

import pytest

from tpv.log.demo import running_example
from tpv.views.abstraction import (
    interval_abstraction,
    kappa,
    local_choice_set,
    local_block,
    parallel_decomposition,
    supports_parallel,
    successor_enabled,
)
from tpv.views.views import induce_views, view_variant_crosstab


@pytest.fixture(scope="module")
def traces():
    log = running_example()
    ts = log.trace_set()
    # order in demo.py: s1..s6
    return {f"s{i + 1}": t for i, t in enumerate(ts)}


def _s(sets):
    return [sorted(x) for x in sets]


def test_successor_enabled_sigma1(traces):
    s1 = traces["s1"]
    assert _s(successor_enabled(s1, i) for i in range(1, 6)) == [
        ["b", "c", "d", "e"],
        ["d", "e"],
        ["f"],
        ["g", "h"],
        [],
    ]


def test_local_choice_sets(traces):
    s1, s3, s5 = traces["s1"], traces["s3"], traces["s5"]
    assert _s(local_choice_set(s1, i) for i in range(1, 6)) == [
        ["o"], ["b", "c"], ["d", "e"], ["f"], ["g", "h"],
    ]
    assert _s(local_choice_set(s3, i) for i in range(1, 6)) == [
        ["o"], ["b", "c"], ["d", "e"], ["f"], ["g", "h"],
    ]
    assert _s(local_choice_set(s5, i) for i in range(1, 6)) == [
        ["o"], ["b"], ["d"], ["f"], ["g", "h"],
    ]


def test_local_blocks_sigma1(traces):
    s1 = traces["s1"]
    blocks = [local_block(s1, i).canonical_str() for i in range(1, 6)]
    assert blocks == ["o", "xor(b, c)", "xor(d, e)", "f", "xor(g, h)"]


def test_parallel_support_differs_between_sigma1_and_sigma3(traces):
    assert supports_parallel(traces["s1"], 2, 3) is True
    assert supports_parallel(traces["s3"], 2, 3) is False


def test_parallel_decomposition(traces):
    assert parallel_decomposition(traces["s1"]) == [(1,), (2, 3), (4,), (5,)]
    assert parallel_decomposition(traces["s3"]) == [(1,), (2,), (3,), (4,), (5,)]
    assert parallel_decomposition(traces["s5"]) == [(1,), (2,), (3,), (4,), (5,)]


def test_interval_abstraction_of_parallel_block(traces):
    assert interval_abstraction(traces["s1"], (2, 3)).canonical_str() == (
        "and(xor(b, c), xor(d, e))"
    )


def test_kappa_per_trace(traces):
    assert kappa(traces["s1"]).canonical_str() == kappa(traces["s2"]).canonical_str()
    assert kappa(traces["s3"]).canonical_str() == kappa(traces["s4"]).canonical_str()
    assert kappa(traces["s5"]).canonical_str() == kappa(traces["s6"]).canonical_str()
    assert kappa(traces["s1"]).canonical_str() == (
        "seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))"
    )
    assert kappa(traces["s3"]).canonical_str() == (
        "seq(o, xor(b, c), xor(d, e), f, xor(g, h))"
    )
    assert kappa(traces["s5"]).canonical_str() == "seq(o, b, d, f, xor(g, h))"


def test_three_views_with_expected_identifiers():
    log = running_example()
    views = induce_views(log)
    got = {v.identifier.canonical_str() for v in views}
    assert got == {
        "seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))",
        "seq(o, xor(b, c), xor(d, e), f, xor(g, h))",
        "seq(o, b, d, f, xor(g, h))",
    }
    assert all(v.frequency == 2 for v in views)


def test_empty_trace_maps_to_epsilon():
    from tpv.log.types import TranslucentLog

    log = TranslucentLog.from_traces([()])
    assert kappa(log.trace_set()[0]).canonical_str() == "epsilon"


def test_crosstab_shared_variant_spans_all_views():
    log = running_example()
    views = induce_views(log)
    ct = view_variant_crosstab(log, views)
    shared = ct.loc["o -> b -> d -> f -> g"]
    assert (shared > 0).sum() == 3  # <o,b,d,f,g> occurs in every view
