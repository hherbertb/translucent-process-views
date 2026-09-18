"""Discovery entry points: per-view models and whole-log models."""

from __future__ import annotations

from typing import Literal, Tuple

import pm4py
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.process_tree.obj import ProcessTree
from pm4py.objects.process_tree.utils import generic as pt_generic

from tpv.discovery.im import VARIANTS, discover_tree
from tpv.log.types import TranslucentLog
from tpv.views.views import ProcessView

ModelMode = Literal["identifier", "translucent_im", "classic_im"]


def discover_process_tree(
    log: TranslucentLog,
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
) -> ProcessTree:
    """Translucent Inductive Miner over a translucent log (see :mod:`tpv.discovery.im`)."""
    tree = discover_tree(log, variant=variant, noise_threshold=noise_threshold)
    tree = pt_generic.fold(tree)
    pt_generic.tree_sort(tree)
    return tree


def discover_petri_net(
    log: TranslucentLog,
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
) -> Tuple[PetriNet, Marking, Marking]:
    tree = discover_process_tree(log, variant=variant, noise_threshold=noise_threshold)
    return pm4py.convert_to_petri_net(tree)


def view_process_tree(
    view: ProcessView,
    mode: ModelMode = "identifier",
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
) -> ProcessTree:
    """Process tree for a single process view.

    * ``identifier`` -- the view's own abstraction identifier as a process tree
      (deterministic, exact for the view; Definition 4.1 / 4.11).
    * ``translucent_im`` -- translucent Inductive Miner on the view's sub-log.
    * ``classic_im`` -- classical Inductive Miner on the executed projection.
    """
    if mode == "identifier":
        tree = view.identifier.to_process_tree()
        tree = pt_generic.fold(tree)
        pt_generic.tree_sort(tree)
        return tree
    if mode == "translucent_im":
        return discover_process_tree(view.sublog, variant=variant, noise_threshold=noise_threshold)
    if mode == "classic_im":
        return discover_process_tree(view.sublog, variant="IM", noise_threshold=noise_threshold)
    raise ValueError(f"unknown mode {mode!r}")


def view_petri_net(
    view: ProcessView,
    mode: ModelMode = "identifier",
    variant: str = "IMtf",
    noise_threshold: float = 0.0,
) -> Tuple[PetriNet, Marking, Marking]:
    return pm4py.convert_to_petri_net(
        view_process_tree(view, mode=mode, variant=variant, noise_threshold=noise_threshold)
    )


__all__ = [
    "VARIANTS",
    "ModelMode",
    "discover_process_tree",
    "discover_petri_net",
    "view_process_tree",
    "view_petri_net",
]
