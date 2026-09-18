"""Process model rendering (Petri net / process tree / BPMN) to SVG via pm4py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pm4py
from pm4py.objects.process_tree.obj import ProcessTree

_FORMATS = ("petri", "tree", "bpmn")


def _write_svg(visualizer, gviz) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "model.svg"
        visualizer.save(gviz, str(out))
        return out.read_text(encoding="utf-8")


def process_tree_svg(tree: ProcessTree) -> str:
    from pm4py.visualization.process_tree import visualizer as pt_vis

    gviz = pt_vis.apply(tree, parameters={"format": "svg"})
    return _write_svg(pt_vis, gviz)


def petri_net_svg(net, im, fm) -> str:
    from pm4py.visualization.petri_net import visualizer as pn_vis

    gviz = pn_vis.apply(net, im, fm, parameters={"format": "svg"})
    return _write_svg(pn_vis, gviz)


def bpmn_svg(tree: ProcessTree) -> str:
    from pm4py.visualization.bpmn import visualizer as bpmn_vis

    bpmn = pm4py.convert_to_bpmn(tree)
    gviz = bpmn_vis.apply(bpmn, parameters={"format": "svg"})
    return _write_svg(bpmn_vis, gviz)


def model_svg(tree: ProcessTree, kind: str = "petri") -> str:
    if kind == "tree":
        return process_tree_svg(tree)
    if kind == "bpmn":
        return bpmn_svg(tree)
    net, im, fm = pm4py.convert_to_petri_net(tree)
    return petri_net_svg(net, im, fm)


__all__ = ["model_svg", "process_tree_svg", "petri_net_svg", "bpmn_svg", "_FORMATS"]
