"""ServiceDesk case-study figure (paper Sect. "Case Study: Sensitivity to Noise").

Renders, as Petri nets:

  * ``servicedesk_global.pdf``          -- one model mined from the whole log with the
                                          translucent Inductive Miner (IMtf); the four
                                          hidden roles are conflated into a single,
                                          visibly loose model.
  * ``servicedesk_kappa_<role>.pdf``    -- the model of each process view kappa induces,
                                          taken straight from the view's abstraction
                                          identifier (deterministic, exact for the view).

This supersedes ``make_servicedesk_workflow.py`` (a hand-drawn control-flow diagram):
the figure is now the method's actual output rather than a drawing of the ground truth.

Standalone -- not part of ``evaluation/run_evaluation.py``.  Needs the Graphviz binary
(``dot``); on this machine it lives in ``C:\\Program Files\\Graphviz\\bin``.

    venv/Scripts/python figures/make_servicedesk_petrinets.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

# pm4py shells out to `dot`; make sure the Graphviz binary is on PATH.
for _cand in (r"C:\Program Files\Graphviz\bin", r"C:\Program Files (x86)\Graphviz\bin"):
    if os.path.isdir(_cand) and _cand not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _cand

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pm4py  # noqa: E402

from tpv.discovery.api import discover_petri_net, view_petri_net  # noqa: E402
from tpv.log.tasks import task_mining_servicedesk  # noqa: E402
from tpv.views.views import induce_views  # noqa: E402

OUT = Path(__file__).resolve().parent


def _save(net, im, fm, name: str) -> None:
    path = OUT / f"{name}.pdf"
    # font_size flows through to the Graphviz visualizer (Parameters.FONT_SIZE);
    # 18 keeps the activity labels legible when the figure is scaled down to
    # column / text width in the paper.
    pm4py.save_vis_petri_net(
        net, im, fm, str(path), rankdir="LR", bgcolor="white", font_size=18
    )
    print(f"  wrote {path.name}")


def main() -> None:
    log, gt, _attrs = task_mining_servicedesk(250, seed=1, noise=0.0)

    print("global model (roles conflated, IMtf):")
    net, im, fm = discover_petri_net(log, variant="IMtf")
    _save(net, im, fm, "servicedesk_global")

    print("kappa per-view models (identifier):")
    for v in induce_views(log):
        role = Counter(
            gt[c] for t in v.traces for c in log.case_ids[t]
        ).most_common(1)[0][0]
        net, im, fm = view_petri_net(v, mode="identifier")
        _save(net, im, fm, f"servicedesk_kappa_{role}")
        print(f"    {v.label} = {role:11s} {v.identifier.canonical_str()}")


if __name__ == "__main__":
    main()
