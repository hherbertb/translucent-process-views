"""Synthetic task-mining helpdesk log and the broadened evaluation registry."""

import pytest

from tpv.discovery.api import view_process_tree
from tpv.quality.agreement import adjusted_rand_index
from tpv.log.tasks import (
    helpdesk_screen_map,
    servicedesk_screen_map,
    task_mining_helpdesk,
    task_mining_servicedesk,
)
from tpv.log.types import executed_projection
from tpv.views.views import induce_views


def _case_labels(log, views):
    t2v = {t: v.label for v in views for t in v.traces}
    return {cid: t2v[t] for t in log.trace_set() for cid in log.case_ids[t]}


def _majority_role(log, view, gt):
    from collections import Counter

    c = Counter(gt[cid] for t in view.traces for cid in log.case_ids[t])
    return c.most_common(1)[0][0]


@pytest.mark.parametrize("rework", [False, True])
def test_helpdesk_recovers_two_roles(rework):
    log, gt = task_mining_helpdesk(60, 40, noise=0.0, rework=rework)
    views = induce_views(log)
    assert len(views) == 2
    pred = _case_labels(log, views)
    keys = list(gt)
    assert adjusted_rand_index([gt[k] for k in keys], [pred[k] for k in keys]) == 1.0


def test_supervisor_view_exposes_privileged_actions():
    log, gt = task_mining_helpdesk(60, 40, noise=0.0)
    views = induce_views(log)
    by_role = {_majority_role(log, v, gt): v.identifier.canonical_str() for v in views}
    assert "escalate" in by_role["supervisor"]
    assert "approve_refund" in by_role["supervisor"]
    assert "escalate" not in by_role["agent"]
    assert "approve_refund" not in by_role["agent"]


def test_same_executed_sequence_spans_both_views():
    log, gt = task_mining_helpdesk(60, 40, noise=0.0)
    views = induce_views(log)
    variant_views = {}
    for v in views:
        for t in v.traces:
            variant_views.setdefault(executed_projection(t), set()).add(v.label)
    shared = [seq for seq, labels in variant_views.items() if len(labels) > 1]
    assert shared, "expected a classical variant present in both the agent and supervisor view"


def test_rework_adds_request_info_to_agent_view_only():
    log, gt = task_mining_helpdesk(60, 40, noise=0.0, rework=True)
    views = induce_views(log)
    by_role = {_majority_role(log, v, gt): v.identifier.canonical_str() for v in views}
    assert "request_info" in by_role["agent"]
    assert "request_info" not in by_role["supervisor"]


def test_screen_map_marks_privileged_actions():
    smap = helpdesk_screen_map()
    assert "escalate" in smap["triage"]["supervisor"]
    assert "escalate" not in smap["triage"]["agent"]


def test_servicedesk_recovers_four_roles():
    log, gt, attrs = task_mining_servicedesk(120, seed=1, noise=0.0)
    views = induce_views(log)
    assert len(views) == 4
    pred = _case_labels(log, views)
    keys = list(gt)
    assert adjusted_rand_index([gt[k] for k in keys], [pred[k] for k in keys]) == 1.0
    assert len(log.classical_variants()) > 4 * 10
    by = {_majority_role(log, v, gt): v.identifier.canonical_str() for v in views}
    assert "approve" in by["supervisor"] and "force_close" in by["supervisor"]
    assert "approve" not in by["agent"]
    assert set(attrs) == {cid for t in log.trace_set() for cid in log.case_ids[t]}


def test_servicedesk_noise_degrades_kappa():
    from evaluation import methods as M
    from evaluation.metrics_eval import recovery

    clean, gt0, _ = task_mining_servicedesk(120, seed=1, noise=0.0)
    noisy, gt2, _ = task_mining_servicedesk(120, seed=1, noise=0.3)
    ari0 = recovery(dict(gt0), M.to_case_labels(clean, M.group_kappa(clean)))["ari"]
    ari2 = recovery(dict(gt2), M.to_case_labels(noisy, M.group_kappa(noisy)))["ari"]
    assert ari0 == 1.0 and ari2 < 0.5


def test_servicedesk_screen_map():
    smap = servicedesk_screen_map()
    assert "approve" in smap["action"]["supervisor"]
    assert "approve" not in smap["action"]["agent"]
    assert smap["triage"]["specialist"] == set()
    assert smap["close"]["specialist"] == set()


def test_global_model_less_precise_than_per_view():
    from tpv.quality.metrics import global_vs_views

    log, _ = task_mining_helpdesk(80, 55, noise=0.0)
    views = induce_views(log)
    frame = global_vs_views(log, views, view_mode="identifier")
    agg = frame[frame["view"] == "AGGREGATE"].set_index("scope")
    assert agg.loc["per-view", "precision"] >= agg.loc["global", "precision"]


def test_evaluation_registry_builds_all_logs():
    from tpv.log.synth import LOG_SPECS, build_all

    names = {s["name"] for s in LOG_SPECS}
    assert {"running_example", "k_view_k4", "partial_parallel", "enterprise",
            "hidden_context", "task_mining_helpdesk", "loop_process"} <= names
    for name, log, gt, attrs in build_all(quick=True):
        assert log.n_cases > 0
        if gt is not None:
            got = {cid for t in log.trace_set() for cid in log.case_ids[t]}
            assert set(gt) == got
            assert attrs is not None and set(attrs) == got
