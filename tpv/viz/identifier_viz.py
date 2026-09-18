"""Abstraction identifier as a nested block diagram (Graphviz).

``seq`` becomes a left-to-right chain, ``xor`` a stack fed by a diamond, ``and`` a
stack fed by a bar -- the way block-structured process models are usually drawn.
"""

from __future__ import annotations

import graphviz

from tpv.views.identifier import Act, And, Empty, Identifier, Seq, Xor
from tpv.viz.theme import activity_colors, text_on


def _collect_activities(node: Identifier, acc: set) -> None:
    if isinstance(node, Act):
        acc.add(node.name)
    elif isinstance(node, Seq):
        for c in node.children:
            _collect_activities(c, acc)
    elif isinstance(node, (Xor, And)):
        for m in node.members:
            _collect_activities(m, acc)


def identifier_graph(identifier: Identifier, rankdir: str = "LR") -> graphviz.Digraph:
    acts: set = set()
    _collect_activities(identifier, acts)
    colors = activity_colors(acts)
    g = graphviz.Digraph("identifier")
    g.attr(rankdir=rankdir, bgcolor="transparent")
    g.attr("node", fontname="Helvetica", fontsize="12")
    g.attr("edge", arrowsize="0.7", color="#888888")
    counter = {"n": 0}

    def fresh(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}{counter['n']}"

    def emit(node: Identifier) -> tuple[str, str]:
        """Return (entry_node_id, exit_node_id) for ``node``."""
        if isinstance(node, Empty):
            nid = fresh("eps")
            g.node(nid, "&tau;", shape="circle", width="0.3", style="filled",
                   fillcolor="#dddddd")
            return nid, nid
        if isinstance(node, Act):
            nid = fresh("a")
            fill = colors.get(node.name, "#4C78A8")
            g.node(nid, node.name, shape="box", style="rounded,filled",
                   fillcolor=fill, fontcolor=text_on(fill))
            return nid, nid
        if isinstance(node, Seq):
            first_in = last_out = None
            prev_out = None
            for child in node.children:
                cin, cout = emit(child)
                if first_in is None:
                    first_in = cin
                if prev_out is not None:
                    g.edge(prev_out, cin)
                prev_out = cout
            return first_in, prev_out
        # Xor / And
        gate_in = fresh("gin")
        gate_out = fresh("gout")
        if isinstance(node, Xor):
            g.node(gate_in, "&times;", shape="diamond", width="0.3",
                   style="filled", fillcolor="#ffffff")
            g.node(gate_out, "&times;", shape="diamond", width="0.3",
                   style="filled", fillcolor="#ffffff")
        else:
            g.node(gate_in, "", shape="box", width="0.08", height="0.5",
                   style="filled", fillcolor="#333333")
            g.node(gate_out, "", shape="box", width="0.08", height="0.5",
                   style="filled", fillcolor="#333333")
        for member in node.members:
            min_, mout = emit(member)
            g.edge(gate_in, min_)
            g.edge(mout, gate_out)
        return gate_in, gate_out

    start = fresh("start")
    end = fresh("end")
    g.node(start, "", shape="circle", width="0.2", style="filled", fillcolor="#000000")
    g.node(end, "", shape="doublecircle", width="0.2", style="filled",
           fillcolor="#000000")
    entry, exit_ = emit(identifier)
    g.edge(start, entry)
    g.edge(exit_, end)
    return g


def identifier_svg(identifier: Identifier, rankdir: str = "LR") -> str:
    return identifier_graph(identifier, rankdir=rankdir).pipe(format="svg").decode("utf-8")


__all__ = ["identifier_graph", "identifier_svg"]
