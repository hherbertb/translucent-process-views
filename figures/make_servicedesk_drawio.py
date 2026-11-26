r"""Editable draw.io (mxGraph) exports of the ServiceDesk case-study models, plus a
hand-built **de-jure** Petri net of the whole service-desk workflow.

Outputs (all in ``figures/``):

  * ``servicedesk_dejure.pdf``      -- the designed (de-jure) workflow: the *union* of
                                      what all four roles can do, with the four
                                      diverging regions (triage / diagnosis / action /
                                      close) boxed and annotated with the per-role
                                      behaviour.  This is subfigure (a) of the paper's
                                      case-study figure.
  * ``servicedesk_dejure.drawio``   -- the same net as an editable draw.io file
                                      (coloured note boxes over each region).
  * ``servicedesk_global.drawio``   -- editable copy of the mined global model.
  * ``servicedesk_kappa_<role>.drawio`` -- editable copy of each model kappa induces.

The ``.drawio`` files take their node coordinates from Graphviz ``dot`` (``plain``
format), so they open with a sensible layout and can then be polished by hand.

Standalone -- not part of ``evaluation/run_evaluation.py``.  Needs the Graphviz binary
(``dot``); on this machine it lives in ``C:\Program Files\Graphviz\bin``.

    venv/Scripts/python figures/make_servicedesk_drawio.py
"""

from __future__ import annotations

import html
import os
import shlex
import sys
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# pm4py / graphviz shell out to `dot`; make sure the binary is on PATH.
for _cand in (r"C:\Program Files\Graphviz\bin", r"C:\Program Files (x86)\Graphviz\bin"):
    if os.path.isdir(_cand) and _cand not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _cand

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import graphviz  # noqa: E402

from pm4py.visualization.petri_net import visualizer as pn_vis  # noqa: E402
from pm4py.visualization.petri_net.variants import wo_decoration as _wo  # noqa: E402

from tpv.discovery.api import discover_petri_net, view_petri_net  # noqa: E402
from tpv.log.tasks import _SD_MODES, _SD_ROLES  # noqa: E402
from tpv.log.tasks import task_mining_servicedesk  # noqa: E402
from tpv.views.views import induce_views  # noqa: E402

_P = _wo.Parameters
OUT = Path(__file__).resolve().parent

# points -> drawio px; drawio is comfortable a little larger than Graphviz points.
_SCALE = 1.4
_FONT = 15


# --------------------------------------------------------------------------- #
#  Graphviz "plain" -> draw.io                                                #
# --------------------------------------------------------------------------- #
def _plain(gviz: graphviz.Digraph):
    """Parse the Graphviz ``plain`` dump of ``gviz`` into (nodes, edges, size).

    nodes: name -> dict(x, y, w, h, label, shape, fill)   (points, origin bottom-left)
    edges: list of dict(tail, head, pts=[(x, y), ...])
    size:  (width, height) in points
    """
    txt = gviz.pipe(format="plain").decode("utf-8", "replace")
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    width = height = 0.0
    for line in txt.splitlines():
        if not line.strip():
            continue
        tok = shlex.split(line)
        kind = tok[0]
        if kind == "graph":
            _, _scale, w, h = tok[:4]
            width, height = float(w) * 72.0, float(h) * 72.0
        elif kind == "node":
            name = tok[1]
            x, y, w, h = (float(v) * 72.0 for v in tok[2:6])
            label = tok[6]
            shape = tok[8] if len(tok) > 8 else "ellipse"
            fill = tok[10] if len(tok) > 10 else "white"
            nodes[name] = dict(x=x, y=y, w=w, h=h, label=label, shape=shape, fill=fill)
        elif kind == "edge":
            tail, head, npts = tok[1], tok[2], int(tok[3])
            coords = tok[4 : 4 + 2 * npts]
            pts = [
                (float(coords[i]) * 72.0, float(coords[i + 1]) * 72.0)
                for i in range(0, 2 * npts, 2)
            ]
            edges.append(dict(tail=tail, head=head, pts=pts))
    return nodes, edges, (width, height)


def _cell(cid, value, style, x, y, w, h, parent="1", vertex=True):
    geo = f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/>'
    return (
        f'        <mxCell id="{cid}" value="{xml_escape(value)}" style="{style}" '
        f'vertex="1" parent="{parent}">\n{geo}\n        </mxCell>'
    )


def _edge_cell(cid, src, dst, parent="1"):
    style = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;"
    return (
        f'        <mxCell id="{cid}" style="{style}" edge="1" parent="{parent}" '
        f'source="{src}" target="{dst}">\n'
        f'          <mxGeometry relative="1" as="geometry"/>\n'
        f'        </mxCell>'
    )


_PLACE = "ellipse;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#333333;"
_TRANS = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#333333;"
_SILENT = "rounded=0;whiteSpace=wrap;html=1;fillColor=#000000;strokeColor=#000000;fontColor=#ffffff;"


def _is_silent(node: dict) -> bool:
    lbl = node["label"].strip().lower()
    fill = node["fill"].strip().lower()
    return node["shape"] in ("box", "rect", "rectangle") and (
        lbl in ("", " ", "tau", "&nbsp;", "\\n") or fill in ("black", "#000000")
    )


def _to_drawio(name: str, gviz: graphviz.Digraph, notes=None) -> str:
    """Serialise ``gviz`` to a draw.io document string.

    ``notes`` is an optional list of ``(node_names, text, colour)`` -- each becomes a
    translucent rounded box drawn just above the bounding box of those nodes.
    """
    nodes, edges, (_w, gh) = _plain(gviz)

    def fx(x):
        return x * _SCALE

    def fy(y):
        return (gh - y) * _SCALE  # flip: Graphviz origin is bottom-left

    body: list[str] = []
    ids: dict[str, str] = {}
    for i, (nm, nd) in enumerate(nodes.items()):
        cid = f"n{i}"
        ids[nm] = cid
        w, h = nd["w"] * _SCALE, nd["h"] * _SCALE
        if nd["shape"] == "ellipse":
            style = _PLACE
            w = h = max(w, h, 30)
        elif _is_silent(nd):
            style = _SILENT
        else:
            style = _TRANS
        label = "" if _is_silent(nd) else html.unescape(nd["label"]).strip('"')
        body.append(
            _cell(cid, label, style, fx(nd["x"]) - w / 2, fy(nd["y"]) - h / 2, w, h)
        )

    for j, ed in enumerate(edges):
        if ed["tail"] in ids and ed["head"] in ids:
            body.append(_edge_cell(f"e{j}", ids[ed["tail"]], ids[ed["head"]]))

    for k, (names, text, colour) in enumerate(notes or []):
        pts = [nodes[n] for n in names if n in nodes]
        if not pts:
            continue
        x0 = min(p["x"] - p["w"] / 2 for p in pts)
        x1 = max(p["x"] + p["w"] / 2 for p in pts)
        ytop = max(p["y"] + p["h"] / 2 for p in pts)
        style = (
            f"rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor={colour};"
            f"strokeColor=#666666;opacity=60;verticalAlign=top;fontSize={_FONT};"
        )
        bx = fx(x0) - 10
        bw = fx(x1) - fx(x0) + 20
        by = fy(ytop) - 62
        body.append(_cell(f"note{k}", text, style, bx, by, max(bw, 160), 52))

    inner = "\n".join(body)
    return (
        '<mxfile host="app.diagrams.net" modified="0" agent="make_servicedesk_drawio.py">\n'
        f'  <diagram id="{name}" name="{name}">\n'
        '    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        'pageWidth="1600" pageHeight="900" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f"{inner}\n"
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )


# --------------------------------------------------------------------------- #
#  de-jure model: the union workflow, with the diverging regions annotated    #
# --------------------------------------------------------------------------- #
_PLACE_ATTR = dict(shape="circle", label="", width="0.35", fixedsize="true")
_TRANS_ATTR = dict(shape="box", style="filled", fillcolor="#eeeeee", fontsize="16")
_TAU_ATTR = dict(
    shape="box", style="filled", fillcolor="#000000", fontcolor="#ffffff",
    label="", width="0.30", height="0.30", fixedsize="true",
)

_REGION_COLOUR = {
    "triage": "#1b9e77",
    "diagnosis": "#d95f02",
    "action": "#7570b3",
    "close": "#e7298a",
}
_REGION_NOTE = {
    "triage": "triage  \u2014  agent: sequential   \u00b7   senior / supervisor: parallel   \u00b7   specialist: skipped",
    "diagnosis": "diagnosis  \u2014  agent / supervisor: check_kb only   \u00b7   specialist: run_diag + remote   \u00b7   senior: all three (parallel)",
    "action": "action  \u2014  one option fires;  senior / specialist also see escalate,  supervisor sees approve,  agent neither",
    "close": "close  \u2014  agent: resolve only   \u00b7   senior: resolve / close_noaction   \u00b7   supervisor: + force_close   \u00b7   specialist: skipped",
}


def _dejure_digraph() -> graphviz.Digraph:
    """The designed service-desk workflow as one Petri net (union over all roles).

    open -> [triage: (categorize || set_priority) or skip]
         -> [diagnosis: (check_kb || run_diag || remote), each optional]
         -> [action: xor(apply_fix, request_info, escalate, approve)]
         -> [close: xor(resolve, close_noaction, force_close) or skip]
         -> log_time -> notify
    """
    g = graphviz.Digraph("servicedesk_dejure", format="pdf")
    g.attr(rankdir="LR", bgcolor="white", nodesep="0.35", ranksep="0.5")
    g.attr("edge", arrowsize="0.8")

    # -- backbone places -----------------------------------------------------
    for p in ("p_start", "p_open", "p_tri", "p_diag", "p_act", "p_close", "p_wrap", "p_end"):
        g.node(p, **_PLACE_ATTR)
    g.node("p_start", **{**_PLACE_ATTR, "fillcolor": "#cfe8cf", "style": "filled"})
    g.node("p_end", **{**_PLACE_ATTR, "fillcolor": "#f2c9c9", "style": "filled"})

    g.node("open", "open", **_TRANS_ATTR)
    g.edge("p_start", "open")
    g.edge("open", "p_open")

    # -- triage region -----------------------------------------------------
    with g.subgraph(name="cluster_triage") as c:
        c.attr(label=_REGION_NOTE["triage"], color=_REGION_COLOUR["triage"],
               style="rounded", fontsize="15", fontcolor=_REGION_COLOUR["triage"], penwidth="2")
        c.node("t_tri_split", **_TAU_ATTR)
        c.node("t_tri_join", **_TAU_ATTR)
        c.node("t_tri_skip", **_TAU_ATTR)
        c.node("q_cat_a", **_PLACE_ATTR)
        c.node("q_cat_b", **_PLACE_ATTR)
        c.node("q_pri_a", **_PLACE_ATTR)
        c.node("q_pri_b", **_PLACE_ATTR)
        c.node("categorize", "categorize", **_TRANS_ATTR)
        c.node("set_priority", "set_priority", **_TRANS_ATTR)
    g.edge("p_open", "t_tri_split")
    g.edge("p_open", "t_tri_skip")
    g.edge("t_tri_skip", "p_tri")
    g.edge("t_tri_split", "q_cat_a")
    g.edge("t_tri_split", "q_pri_a")
    g.edge("q_cat_a", "categorize")
    g.edge("categorize", "q_cat_b")
    g.edge("q_pri_a", "set_priority")
    g.edge("set_priority", "q_pri_b")
    g.edge("q_cat_b", "t_tri_join")
    g.edge("q_pri_b", "t_tri_join")
    g.edge("t_tri_join", "p_tri")

    # -- diagnosis region -------------------------------------------------
    with g.subgraph(name="cluster_diagnosis") as c:
        c.attr(label=_REGION_NOTE["diagnosis"], color=_REGION_COLOUR["diagnosis"],
               style="rounded", fontsize="15", fontcolor=_REGION_COLOUR["diagnosis"], penwidth="2")
        c.node("t_diag_split", **_TAU_ATTR)
        c.node("t_diag_join", **_TAU_ATTR)
        for a in ("check_kb", "run_diag", "remote"):
            c.node(f"d_{a}_a", **_PLACE_ATTR)
            c.node(f"d_{a}_b", **_PLACE_ATTR)
            c.node(a, a, **_TRANS_ATTR)
            c.node(f"t_skip_{a}", **_TAU_ATTR)
    g.edge("p_tri", "t_diag_split")
    for a in ("check_kb", "run_diag", "remote"):
        g.edge("t_diag_split", f"d_{a}_a")
        g.edge(f"d_{a}_a", a)
        g.edge(a, f"d_{a}_b")
        g.edge(f"d_{a}_a", f"t_skip_{a}")
        g.edge(f"t_skip_{a}", f"d_{a}_b")
        g.edge(f"d_{a}_b", "t_diag_join")
    g.edge("t_diag_join", "p_diag")

    # -- action region (xor) --------------------------------------------
    with g.subgraph(name="cluster_action") as c:
        c.attr(label=_REGION_NOTE["action"], color=_REGION_COLOUR["action"],
               style="rounded", fontsize="15", fontcolor=_REGION_COLOUR["action"], penwidth="2")
        for a in ("apply_fix", "request_info", "escalate", "approve"):
            c.node(a, a, **_TRANS_ATTR)
    for a in ("apply_fix", "request_info", "escalate", "approve"):
        g.edge("p_diag", a)
        g.edge(a, "p_act")

    # -- close region (xor + skip) ------------------------------------
    with g.subgraph(name="cluster_close") as c:
        c.attr(label=_REGION_NOTE["close"], color=_REGION_COLOUR["close"],
               style="rounded", fontsize="15", fontcolor=_REGION_COLOUR["close"], penwidth="2")
        for a in ("resolve", "close_noaction", "force_close"):
            c.node(a, a, **_TRANS_ATTR)
        c.node("t_close_skip", **_TAU_ATTR)
    for a in ("resolve", "close_noaction", "force_close"):
        g.edge("p_act", a)
        g.edge(a, "p_close")
    g.edge("p_act", "t_close_skip")
    g.edge("t_close_skip", "p_close")

    # -- wrap-up ---------------------------------------------------------
    g.node("log_time", "log_time", **_TRANS_ATTR)
    g.node("notify", "notify", **_TRANS_ATTR)
    g.edge("p_close", "log_time")
    g.edge("log_time", "p_wrap")
    g.edge("p_wrap", "notify")
    g.edge("notify", "p_end")
    return g


_DEJURE_NOTES = [
    (["categorize", "set_priority", "t_tri_split", "t_tri_skip"],
     _REGION_NOTE["triage"], "#d7efe4"),
    (["check_kb", "run_diag", "remote", "t_diag_split"],
     _REGION_NOTE["diagnosis"], "#fbe4d3"),
    (["apply_fix", "request_info", "escalate", "approve"],
     _REGION_NOTE["action"], "#e2e0f0"),
    (["resolve", "close_noaction", "force_close", "t_close_skip"],
     _REGION_NOTE["close"], "#f7d9ea"),
]


# --------------------------------------------------------------------------- #
def _mined_digraph(net, im, fm) -> graphviz.Digraph:
    return pn_vis.apply(
        net, im, fm,
        variant=pn_vis.Variants.WO_DECORATION,
        parameters={_P.FORMAT: "png", _P.RANKDIR: "LR", _P.FONT_SIZE: 16},
    )


def main() -> None:
    log, gt, _attrs = task_mining_servicedesk(250, seed=1, noise=0.0)

    # -- de-jure model -------------------------------------------------------
    dg = _dejure_digraph()
    pdf_path = dg.render(filename="servicedesk_dejure", directory=str(OUT), cleanup=True)
    print(f"  wrote {Path(pdf_path).name}")
    (OUT / "servicedesk_dejure.drawio").write_text(
        _to_drawio("servicedesk_dejure", dg, notes=_DEJURE_NOTES), encoding="utf-8"
    )
    print("  wrote servicedesk_dejure.drawio")

    # -- global mined model ----------------------------------------------
    net, im, fm = discover_petri_net(log, variant="IMtf")
    (OUT / "servicedesk_global.drawio").write_text(
        _to_drawio("servicedesk_global", _mined_digraph(net, im, fm)), encoding="utf-8"
    )
    print("  wrote servicedesk_global.drawio")

    # -- kappa per-view models -----------------------------------------
    for v in induce_views(log):
        role = Counter(
            gt[c] for t in v.traces for c in log.case_ids[t]
        ).most_common(1)[0][0]
        net, im, fm = view_petri_net(v, mode="identifier")
        (OUT / f"servicedesk_kappa_{role}.drawio").write_text(
            _to_drawio(f"servicedesk_kappa_{role}", _mined_digraph(net, im, fm)),
            encoding="utf-8",
        )
        print(f"  wrote servicedesk_kappa_{role}.drawio")

    _ = (_SD_MODES, _SD_ROLES, html)  # kept for reference / future annotation tweaks


if __name__ == "__main__":
    main()
