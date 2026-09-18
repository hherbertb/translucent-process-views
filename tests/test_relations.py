"""Translucent activity relationships and DFGs."""

from tpv.discovery import relations as rel
from tpv.discovery.dfg import classical_dfg, project_log, translucent_dfg
from tpv.log.demo import running_example


def test_start_and_end_activities():
    log = running_example()
    assert rel.start_activities(log) == {"o"}
    assert rel.end_activities(log) == {"g", "h"}


def test_parallel_relation_present_for_running_example():
    log = running_example()
    par = rel.parallel(log)
    # b and d are enabled together in sigma1 (b executed, d still enabled next)
    assert "d" in par.get("b", set()) or "b" in par.get("d", set())


def test_choice_relation_symmetric():
    log = running_example()
    ch = rel.choice(log)
    assert "c" in ch.get("b", set())
    assert "b" in ch.get("c", set())


def test_translucent_dfg_superset_of_classical_edges():
    log = running_example()
    c = classical_dfg(log)
    t = translucent_dfg(log)
    assert set(c.edges).issubset(set(t.edges))


def test_project_log_restricts_enabled_sets():
    log = running_example()
    projected = project_log(log, {"o", "b", "d"})
    for trace in projected.trace_set():
        for _act, enabled in trace:
            assert enabled <= {"o", "b", "d"}
