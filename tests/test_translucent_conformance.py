"""Vendored translucent fitness / precision and their wiring into metrics."""

import math

from tpv.discovery.api import discover_petri_net
from tpv.log.demo import loop_process_log, running_example
from tpv.quality.metrics import global_vs_views, model_quality
from tpv.quality.translucent import translucent_conformance
from tpv.views.views import induce_views


def _finite01(x):
    return isinstance(x, float) and not math.isnan(x) and 0.0 - 1e-9 <= x <= 1.0 + 1e-9


def test_translucent_conformance_on_running_example():
    log = running_example()
    net, im, fm = discover_petri_net(log, variant="IMtf")
    tc = translucent_conformance(log, net, im, fm)
    assert _finite01(tc["translucent_fitness"])
    assert _finite01(tc["translucent_precision"])


def test_translucent_conformance_on_loop_process():
    log = loop_process_log(60)
    net, im, fm = discover_petri_net(log, variant="IMtf")
    tc = translucent_conformance(log, net, im, fm)
    assert _finite01(tc["translucent_fitness"])
    assert _finite01(tc["translucent_precision"])


def test_model_quality_translucent_flag_populates_fields():
    log = running_example()
    net, im, fm = discover_petri_net(log, variant="IMtf")
    q = model_quality(log, net, im, fm, translucent=True)
    assert q.translucent_fitness is not None and _finite01(q.translucent_fitness)
    assert q.translucent_precision is not None and _finite01(q.translucent_precision)
    assert "translucent_fitness" in q.as_dict()

    q0 = model_quality(log, net, im, fm, translucent=False)
    assert q0.translucent_fitness is None
    assert "translucent_fitness" not in q0.as_dict()


def test_global_vs_views_includes_translucent_columns():
    log = running_example()
    views = induce_views(log)
    frame = global_vs_views(log, views, view_mode="identifier", translucent=True)
    assert {"translucent_fitness", "translucent_precision"} <= set(frame.columns)
    agg = frame[frame["view"] == "AGGREGATE"]
    assert agg["translucent_precision"].notna().all()
