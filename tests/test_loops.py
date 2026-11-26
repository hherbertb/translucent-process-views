"""The loop extension of Definition 4.1 (``loop``) and its folding (Def. 4.15).

Two properties carry the extension, and both are checked here:

* it repairs the stated limitation -- the number of views no longer grows with
  the number of loop iterations, and
* it changes nothing else -- every identifier of a trace without repetition is
  the identifier Definition 4.10 produces, the running example included.
"""

import pytest

from pm4py.objects.process_tree.obj import Operator

from tpv.log.demo import loop_process_log, running_example
from tpv.views.abstraction import fold_loops, kappa
from tpv.views.identifier import Loop, act, and_, loop, seq
from tpv.views.views import induce_views


# -- the identifier ----------------------------------------------------------
def test_loop_canonical_string():
    assert loop(act("a")).canonical_str() == "loop(a)"
    assert loop(seq(act("a"), act("b"))).canonical_str() == "loop(seq(a, b))"


def test_loop_identity_is_canonical_string():
    assert loop(and_(act("a"), act("b"))) == loop(and_(act("b"), act("a")))
    assert loop(act("a")) != act("a")


def test_nested_loop_collapses():
    assert loop(loop(act("a"))) == loop(act("a"))


def test_loop_of_empty_degrades():
    from tpv.views.identifier import Empty
    assert isinstance(loop(Empty()), Empty)


def test_loop_process_tree_is_body_then_silent_redo():
    tree = loop(act("a")).to_process_tree()
    assert tree.operator is Operator.LOOP
    assert len(tree.children) == 2
    assert tree.children[0].label == "a"
    assert tree.children[1].label is None       # tau: "one or more times"


# -- the folding -------------------------------------------------------------
def test_fold_needs_two_executions():
    a, b = act("a"), act("b")
    assert fold_loops([a, b]) == [a, b]
    assert fold_loops([a, a]) == [loop(a)]
    assert fold_loops([a, a, a]) == [loop(a)]


def test_fold_takes_the_primitive_period():
    """``B B B B`` must fold like ``B B B``, not into ``loop(seq(B, B))``."""
    b = act("b")
    assert fold_loops([b] * 4) == fold_loops([b] * 3) == [loop(b)]


def test_fold_multi_block_pattern():
    a, b, c = act("a"), act("b"), act("c")
    assert fold_loops([a, b, a, b, c]) == [loop(seq(a, b)), c]


def test_fold_leaves_a_partial_repetition_alone():
    a, b = act("a"), act("b")
    assert fold_loops([a, b, a, b, a]) == [loop(seq(a, b)), a]


def test_fold_rejects_unknown_mode():
    with pytest.raises(ValueError):
        fold_loops([act("a"), act("a")], mode="sometimes")


# -- on the log the limitation was stated for --------------------------------
@pytest.mark.parametrize("max_rework", [0, 1, 2, 3, 4, 6, 10])
def test_unrolled_view_count_grows_but_folded_does_not(max_rework):
    log = loop_process_log(600, seed=13, max_rework=max_rework)
    # Definition 4.10: one view per distinct number of iterations, capped by
    # the longest trace the generator produced
    assert len(induce_views(log)) == len({len(t) for t in log.trace_set()})
    # Definition 4.15: constant, whatever the loop bound
    assert len(induce_views(log, loops="strict")) == min(3, max_rework + 1)
    assert len(induce_views(log, loops="enabled")) == min(2, max_rework + 1)


def test_enabled_mode_merges_one_iteration_with_many():
    """The translucent reading: the enabled sets show the loop could continue,
    so running the body once and running it four times is one view."""
    log = loop_process_log(600, seed=13, max_rework=4)
    ident = {kappa(t, loops="enabled").canonical_str() for t in log.trace_set()}
    assert ident == {
        "seq(register, and(decide, xor(assess, request_docs)), archive)",
        "seq(register, loop(and(assess, request_docs)), "
        "and(decide, xor(assess, request_docs)), archive)",
    }


def test_strict_mode_keeps_one_iteration_apart():
    log = loop_process_log(600, seed=13, max_rework=4)
    ident = {kappa(t, loops="strict").canonical_str() for t in log.trace_set()}
    assert len(ident) == 3
    assert sum("loop(" in i for i in ident) == 1


# -- and changes nothing else ------------------------------------------------
def test_running_example_identifiers_unchanged_by_either_mode():
    for trace in running_example().trace_set():
        plain = kappa(trace).canonical_str()
        assert kappa(trace, loops="strict").canonical_str() == plain
        assert kappa(trace, loops="enabled").canonical_str() == plain


def test_kappa_default_does_not_fold():
    log = loop_process_log(200, seed=13, max_rework=4)
    assert not any(isinstance(kappa(t), Loop) for t in log.trace_set())
    assert all("loop(" not in kappa(t).canonical_str() for t in log.trace_set())


def test_loops_true_is_strict():
    log = loop_process_log(200, seed=13, max_rework=4)
    for t in log.trace_set():
        assert kappa(t, loops=True).canonical_str() == kappa(t, loops="strict").canonical_str()


def test_kappa_rejects_unknown_loop_mode():
    trace = next(iter(loop_process_log(10, seed=13, max_rework=2).trace_set()))
    with pytest.raises(ValueError):
        kappa(trace, loops="maybe")
