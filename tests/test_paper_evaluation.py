"""Smoke tests for the paper evaluation harness."""

import random

import pytest

from evaluation import methods as M
from evaluation.metrics_eval import (
    attribute_informativeness,
    enabled_incoherence,
    n_groups,
    recovery,
)
from tpv.log.synth import (
    CLEAN_ATTRS,
    NOISY_ATTRS,
    ORACLE_ATTRS,
    build_all,
    enterprise_log,
    k_view_log,
    partial_parallel_log,
    running_example_log,
)
from tpv.log.demo import running_example
from tpv.views.views import induce_views


def _case_ids(log):
    return {cid for t in log.trace_set() for cid in log.case_ids[t]}


@pytest.mark.parametrize("name,log,gt,attrs", list(build_all(quick=True)))
def test_generator_shape(name, log, gt, attrs):
    assert log.n_cases > 0
    if gt is not None:
        assert set(gt) == _case_ids(log)
        assert len(set(gt.values())) >= 2
        assert attrs is not None
        assert set(attrs) == _case_ids(log)
        sample = next(iter(attrs.values()))
        for field in CLEAN_ATTRS + NOISY_ATTRS + ORACLE_ATTRS:
            assert field in sample
    else:
        assert attrs is None


def test_kappa_recovers_synthetic_ground_truth():
    for fn in (lambda: running_example_log(240, seed=1),
               lambda: k_view_log(4, 60, seed=1),
               lambda: partial_parallel_log(200, seed=1),
               lambda: enterprise_log(250, 5, seed=1)):
        log, gt, _ = fn()
        views = induce_views(log)
        assert len(views) == len(set(gt.values()))
        t2v = {t: v.label for v in views for t in v.traces}
        pred = {cid: t2v[t] for t in log.trace_set() for cid in log.case_ids[t]}
        assert recovery(dict(gt), pred)["ari"] == pytest.approx(1.0)


def test_generators_have_many_variants_per_view():
    """Classical / translucent variants far outnumber the hidden views."""
    log, gt, _ = enterprise_log(400, 5, seed=1)
    k = len(set(gt.values()))
    assert len(log.classical_variants()) > 10 * k
    assert len(log.trace_set()) >= len(log.classical_variants())
    assert len(induce_views(log)) == k


def test_grouping_methods_partition_the_trace_set():
    # D2V-TC needs gensim; without it group_trace2vec_clustering returns None and
    # the baseline vanishes from the paper tables.  Skip with a reason rather
    # than failing on `assert None is not None`, which says nothing useful.
    pytest.importorskip(
        "gensim",
        reason="gensim missing: D2V-TC baseline unavailable, so this environment "
               "cannot reproduce the paper's tables (see requirements.txt)",
    )
    log, gt, attrs = running_example_log(200, seed=2)
    ts = set(log.trace_set())
    k = len(set(gt.values()))
    for name, g in [
        ("global", M.group_global(log)),
        ("kappa", M.group_kappa(log)),
        ("classical", M.group_classical_variants(log)),
        ("translucent", M.group_translucent_variants(log)),
        ("cf_kmeans", M.group_control_flow_clustering(log, k, "kmeans")),
        ("ctx_kmeans", M.group_context_aware_clustering(log, k, "kmeans")),
        ("trace2vec", M.group_trace2vec_clustering(log, k)),
        ("enabled", M.group_enabled_clustering(log, k, "kmeans")),
        ("attr_clean", M.group_attribute_clustering(log, attrs, "clean", k)),
        ("attr_noisy", M.group_attribute_clustering(log, attrs, "noisy", k)),
        ("attr_all", M.group_attribute_clustering(log, attrs, "all", k)),
    ]:
        assert g is not None, name
        assert set(g) == ts, name
    assert n_groups(M.group_global(log)) == 1
    assert n_groups(M.group_translucent_variants(log)) == len(ts)
    assert n_groups(M.group_kappa(log)) == len(induce_views(log))


def test_attribute_clustering_none_without_attrs():
    log, _, _ = running_example_log(120, seed=1)
    assert M.group_attribute_clustering(log, None, "clean", 3) is None


def test_recovery_extremes():
    a = {f"c{i}": i % 3 for i in range(60)}
    assert recovery(a, dict(a))["ari"] == pytest.approx(1.0)
    rnd = random.Random(0)
    b = {k: rnd.randint(0, 2) for k in a}
    assert recovery(a, b)["ari"] < 0.4


def test_role_is_the_label_and_is_never_a_clean_attribute():
    """`role` is the hidden label verbatim, so a baseline given it is an oracle.

    Counting it as a "clean attribute" is what made ATTR-TC clean look like a
    competing baseline that ties kappa at ARI 1.00.
    """
    assert ORACLE_ATTRS == ["role"]
    assert "role" not in CLEAN_ATTRS
    assert "role" not in NOISY_ATTRS
    log, gt, attrs = running_example_log(600, seed=1)
    for cid, label in gt.items():
        assert attrs[cid]["role"] == label


def test_attribute_informativeness_clean_vs_noisy():
    log, gt, attrs = running_example_log(600, seed=1)
    info = attribute_informativeness(attrs, dict(gt))
    # the oracle attribute is perfectly informative -- that is why it is excluded
    # from the clean set rather than reported as a baseline
    assert info["role"] == pytest.approx(1.0, abs=1e-6)
    # the clean attributes are informative but not identifying
    assert all(info[a] < 0.999 for a in CLEAN_ATTRS), {a: info[a] for a in CLEAN_ATTRS}
    assert info["department"] > 0.3
    assert info["noise_score"] < 0.15
    assert info["ticket_channel"] < 0.15
    assert info["flag_a"] < 0.15


def test_clean_attribute_clustering_beats_noisy():
    log, gt, attrs = running_example_log(600, seed=1)
    k = len(set(gt.values()))
    gc = M.group_attribute_clustering(log, attrs, "clean", k)
    gn = M.group_attribute_clustering(log, attrs, "noisy", k)
    ari_clean = recovery(dict(gt), M.to_case_labels(log, gc))["ari"]
    ari_noisy = recovery(dict(gt), M.to_case_labels(log, gn))["ari"]
    assert ari_clean > 0.5
    assert ari_clean > ari_noisy + 0.2


def test_enabled_incoherence_classical_worse_than_kappa():
    log, _, _ = running_example_log(300, seed=1)
    ic_cl = enabled_incoherence(log, M.group_classical_variants(log))["mean_sig_per_variant"]
    ic_kap = enabled_incoherence(log, M.group_kappa(log))["mean_sig_per_variant"]
    assert ic_cl > ic_kap
    assert ic_kap == pytest.approx(1.0)


def _view_identifiers(log):
    return {v.label: v.identifier.canonical_str() for v in induce_views(log)}


def test_running_example_log_is_L_run_at_scale():
    """The scaled generator must induce exactly the three views C1..C3 of
    Section 4.6 -- verbatim, same labels -- as the six-trace demo.running_example().
    Guards the label-string choice and the no-shuffle / view-order in synth.py."""
    small = _view_identifiers(running_example())
    scaled = _view_identifiers(running_example_log(1500, seed=1)[0])
    assert scaled == small
    assert scaled == {
        "C1": "seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))",
        "C2": "seq(o, xor(b, c), xor(d, e), f, xor(g, h))",
        "C3": "seq(o, b, d, f, xor(g, h))",
    }


def test_run_quick_writes_outputs(tmp_path):
    from evaluation.run_evaluation import run

    res = run(quick=True, out=tmp_path / "res", figdir=tmp_path / "fig", seeds=[0])
    for name in ("e1_separation", "e2_quality", "e3_sweeps", "e4_taskmining"):
        assert (tmp_path / "res" / f"{name}.csv").exists()
    for t in ("summary_partition_table", "summary_quality_table",
              "summary_quality_caseweighted_table", "findings"):
        assert (tmp_path / "res" / f"{t}.tex").exists()
    assert {"f1", "translucent_f1", "n_cases"} <= set(res["e2"].columns)
    e2m = set(res["e2"]["method"])
    assert {"translucent_variants", "cf_kmeans@k", "cf_ward@auto"} <= e2m
    attrs_tex = (tmp_path / "res" / "attributes_table.tex").read_text(encoding="utf-8")
    assert "hidden label" in attrs_tex and "hidden $k$" not in attrs_tex
    assert (tmp_path / "fig" / "fig_separation.png").exists()
    assert (tmp_path / "fig" / "fig_recovery.pdf").exists()
    assert (tmp_path / "fig" / "fig_attributes.png").exists()
    assert (tmp_path / "fig" / "fig_perlog.png").exists()
    assert (tmp_path / "fig" / "fig_quality_perlog.png").exists()
    assert (tmp_path / "fig" / "fig_scenario.png").exists()
    assert (tmp_path / "fig" / "fig_scenario_heat.png").exists()
    for t in ("findings_case", "case_study_table"):
        assert (tmp_path / "res" / f"{t}.tex").exists()
    assert (tmp_path / "res" / "e5_case_study.csv").exists()
    e5m = set(res["e5"]["method"])
    assert {"kappa", "kappa_identifier", "translucent_variants",
            "cf_kmeans@auto", "attr_clean@k"} <= e5m
    assert set(res["e3"]["method"]) >= {"kappa", "clustering_mean", "clustering_best"}
    assert not res["e1"].empty and not res["e2"].empty
