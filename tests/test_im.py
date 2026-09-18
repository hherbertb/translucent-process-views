"""The IM variant must match pm4py's Inductive Miner on classical logs."""

import datetime

import pandas as pd
import pm4py
import pytest
from pm4py.algo.discovery.footprints import algorithm as fp_alg

from tpv.discovery.api import discover_process_tree
from tpv.log.demo import hidden_context_log
from tpv.log.types import TranslucentLog
from tpv.views.views import induce_views

CASES = {
    "sequence": {("a", "b", "c", "d"): 10},
    "xor": {("a", "b", "d"): 10, ("a", "c", "d"): 10},
    "parallel": {("a", "b", "c", "d"): 6, ("a", "c", "b", "d"): 6},
    "loop": {
        ("a", "b", "c"): 6,
        ("a", "b", "c", "b", "c"): 6,
        ("a", "b", "c", "b", "c", "b", "c"): 3,
    },
    "optional": {("a", "b", "c"): 10, ("a", "c"): 6},
}


def _tlog(variants):
    entries = []
    for seq, n in variants.items():
        for _ in range(n):
            entries.append(tuple((a, frozenset({a})) for a in seq))
    return TranslucentLog.from_traces(entries)


def _pm_log(variants):
    rows, cid, t0 = [], 0, datetime.datetime(2020, 1, 1)
    for seq, n in variants.items():
        for _ in range(n):
            for i, a in enumerate(seq):
                rows.append(
                    {
                        "case:concept:name": str(cid),
                        "concept:name": a,
                        "time:timestamp": t0 + datetime.timedelta(minutes=i),
                    }
                )
            cid += 1
    return pm4py.format_dataframe(pd.DataFrame(rows))


def _footprint(tree):
    net, im, fm = pm4py.convert_to_petri_net(tree)
    fp = fp_alg.apply(net, im, fm)
    return fp["sequence"], fp["parallel"]


@pytest.mark.parametrize("name", list(CASES))
def test_im_matches_pm4py(name):
    variants = CASES[name]
    mine = discover_process_tree(_tlog(variants), variant="IM")
    ref = pm4py.discover_process_tree_inductive(_pm_log(variants))
    assert _footprint(mine) == _footprint(ref), f"{name}: {mine} != {ref}"


def test_loop_process_yields_a_loop_operator():
    from pm4py.objects.process_tree.obj import Operator

    from tpv.log.demo import loop_process_log

    def has_loop(node):
        return node.operator == Operator.LOOP or any(has_loop(c) for c in node.children)

    log = loop_process_log(120)
    # the executed traces really repeat activities
    assert any(len(t) > 6 for t in log.trace_set())
    assert has_loop(discover_process_tree(log, variant="IMtf"))


def test_translucent_variant_recovers_parallel_in_hidden_context():
    log, _ = hidden_context_log({"admin": 60, "clerk": 0, "auditor": 0})
    admin_view = induce_views(log)[0]
    tree = discover_process_tree(admin_view.sublog, variant="IMtf")
    # b and c are concurrent for the admin role
    _seq, par = _footprint(tree)
    assert ("b", "c") in par and ("c", "b") in par
