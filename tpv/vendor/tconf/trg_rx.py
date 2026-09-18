from collections import deque
from typing import Optional

import rustworkx as rx
from pm4py import PetriNet, Marking
from pm4py.algo.analysis.workflow_net.algorithm import apply as is_workflow_net
from pm4py.objects.log.obj import Trace
from pm4py.objects.petri_net.semantics import enabled_transitions, execute
from pm4py.objects.petri_net.utils.align_utils import SKIP
from pm4py.util.typing import AlignmentResult

from .futils import (
    add_artificial_end_transition,
    ARTIFICIAL_END_TRANSITION_NAME,
    ARTIFICIAL_END_TRANSITION_LABEL,
)

# A model discovered from a sub-log that mixes several behaviours (e.g. a noisy
# or under-separated grouping) can have a very wide concurrency block, so its
# reachability graph -- and, worse, the (|trace|+1) x |TRG| alignment product
# graph -- grows to millions of nodes and the rustworkx backend aborts the whole
# process on a multi-GB allocation (uncatchable from Python).  Past these bounds
# we raise instead; callers score the sub-model with the classical measures only.
_MAX_TRG_NODES = 2_500
_MAX_PRODUCT_NODES = 200_000


def tversky_index(set1: set, set2: set, alpha: float = 1, beta: float = 1) -> float:
    intersection = len(set1.intersection(set2))
    return intersection / (
        intersection
        + alpha * len(set1.difference(set2))
        + beta * len(set2.difference(set1))
    )


class TranslucentReachabilityGraph:
    """
    Reachability graph of a translucent accepting Petri net, backed by a
    rustworkx.PyDiGraph instead of networkx.MultiDiGraph.

    Node payload : {"marking": Marking, "enabled": set[str]}
    Edge payload : {"firing_sequence": tuple[str, ...], "label": str, "cost": int}
    """

    def __init__(self, accepting_petri_net: tuple[PetriNet, Marking, Marking]) -> None:
        if not is_workflow_net(accepting_petri_net[0]):
            raise ValueError("The Petri net is not a workflow net")

        accepting_petri_net = add_artificial_end_transition(accepting_petri_net)
        net = accepting_petri_net[0]

        # multigraph=True (default) allows parallel edges between the same nodes
        self.graph: rx.PyDiGraph = rx.PyDiGraph()
        self.transition_labels: dict[str, str | None] = {
            t.name: t.label for t in net.transitions
        }

        # Add initial (index 0) and final (index 1) nodes first so that
        # rustworkx assigns them indices 0 and 1 in insertion order.
        init_idx: int = self.graph.add_node(
            {"marking": accepting_petri_net[1], "enabled": set()}
        )
        final_idx: int = self.graph.add_node(
            {"marking": accepting_petri_net[2], "enabled": set()}
        )

        self.initial_state: int = init_idx   # 0
        self.final_state: int = final_idx    # 1
        self.marking_map: dict[Marking, int] = {
            accepting_petri_net[1]: init_idx,
            accepting_petri_net[2]: final_idx,
        }

        # ── silent-closure BFS, cached per marking ──────────────────────────
        succ_cache: dict[
            Marking,
            tuple[list[tuple[Marking, tuple[str, ...], str]], set[str]],
        ] = {}

        def successors_from_marking(
            m0: Marking,
        ) -> tuple[list[tuple[Marking, tuple[str, ...], str]], set[str]]:
            if m0 in succ_cache:
                return succ_cache[m0]

            q: deque[tuple[Marking, tuple[str, ...]]] = deque([(m0, ())])
            seen: set[Marking] = {m0}
            arcs: list[tuple[Marking, tuple[str, ...], str]] = []
            enabled_labels: set[str] = set()

            while q:
                m, silent_seq = q.popleft()
                for t in enabled_transitions(net, m):
                    m_next = execute(t, net, m)
                    if t.label is None:                         # silent transition
                        if m_next not in seen:
                            seen.add(m_next)
                            q.append((m_next, silent_seq + (t.name,)))
                    else:                                       # visible transition
                        fs = silent_seq + (t.name,)
                        arcs.append((m_next, fs, t.label))
                        if t.label != ARTIFICIAL_END_TRANSITION_LABEL:
                            enabled_labels.add(t.label)

            succ_cache[m0] = (arcs, enabled_labels)
            return succ_cache[m0]

        # ── main BFS over reachability states ───────────────────────────────
        open_list: list[int] = [init_idx]

        while open_list:
            if self.graph.num_nodes() > _MAX_TRG_NODES:
                raise MemoryError(
                    f"translucent reachability graph exceeded {_MAX_TRG_NODES} "
                    "nodes; model too loose for translucent conformance"
                )
            current_node = open_list.pop()
            current_marking: Marking = self.graph[current_node]["marking"]

            arcs, enabled_labels = successors_from_marking(current_marking)
            self.graph[current_node]["enabled"].update(enabled_labels)

            for post_marking, firing_sequence, label in arcs:
                post_node = self.marking_map.get(post_marking)
                if post_node is None:
                    post_node = self.graph.add_node(
                        {"marking": post_marking, "enabled": set()}
                    )
                    self.marking_map[post_marking] = post_node
                    open_list.append(post_node)

                self.graph.add_edge(
                    current_node,
                    post_node,
                    {
                        "firing_sequence": firing_sequence,
                        "label": label,
                        "cost": 0 if firing_sequence[-1] == ARTIFICIAL_END_TRANSITION_NAME else 1,
                    },
                )

        # ── best-worst cost (Dijkstra on the TRG) ───────────────────────────
        self.best_worst_cost: float = rx.dijkstra_shortest_path_lengths(
            self.graph,
            self.initial_state,
            lambda e: float(e["cost"]),
            goal=self.final_state,
        )[self.final_state]


class TranslucentAlignmentStateGraph:
    """
    Product graph of a TranslucentReachabilityGraph and a trace, backed by a
    rustworkx.PyDiGraph.

    Composite states  : (trace_index, trg_node_index)
    Node payload      : {"marking": Marking, "enabled": set[str]}
    Edge payload      : {"firing_sequence", "label", "cost", "classical_cost", "type"}

    Because rustworkx uses integer node indices, an explicit mapping
        _node_map : (trace_idx, trg_node) -> rx_node_index
    is maintained alongside the graph.
    """

    def __init__(
        self,
        translucent_reachability_graph: TranslucentReachabilityGraph,
        trace: Trace,
    ) -> None:
        self.graph: rx.PyDiGraph = rx.PyDiGraph()
        self.trace = trace
        self.best_worst_cost: float = (
            len(trace) + translucent_reachability_graph.best_worst_cost
        )
        self.transition_labels = translucent_reachability_graph.transition_labels
        trg = translucent_reachability_graph
        n = len(trace)

        if (n + 1) * trg.graph.num_nodes() > _MAX_PRODUCT_NODES:
            raise MemoryError(
                f"alignment product graph would exceed {_MAX_PRODUCT_NODES} "
                f"nodes ({n + 1} x {trg.graph.num_nodes()}); model too loose "
                "for translucent conformance"
            )

        # (trace_idx, trg_node_index) -> rx node index
        self._node_map: dict[tuple[int, int], int] = {}

        def enabled_set_cost(
            enabled_set_trace: set[str], enabled_set_model: set[str]
        ) -> float:
            return 1.0 - tversky_index(enabled_set_trace, enabled_set_model)

        # ── 1. Add all (n+1) × |TRG_nodes| nodes up front ─────────────────
        for idx in range(n + 1):
            for trg_node in trg.graph.node_indices():
                node_data = trg.graph[trg_node]
                rx_idx = self.graph.add_node(
                    {"marking": node_data["marking"], "enabled": node_data["enabled"]}
                )
                self._node_map[(idx, trg_node)] = rx_idx

        self.initial_state: tuple[int, int] = (0, trg.initial_state)
        self.final_state: tuple[int, int] = (n, trg.final_state)
        self._initial_idx: int = self._node_map[self.initial_state]
        self._final_idx: int = self._node_map[self.final_state]

        # Pre-fetch all TRG edges once: (u, v, edge_data)
        trg_edges = trg.graph.weighted_edge_list()

        # ── 2. Model moves (same trace index, traverse a TRG edge) ─────────
        for idx in range(n + 1):
            for u, v, edata in trg_edges:
                self.graph.add_edge(
                    self._node_map[(idx, u)],
                    self._node_map[(idx, v)],
                    {
                        "firing_sequence": edata["firing_sequence"],
                        "label": None,
                        "cost": edata["cost"],
                        "classical_cost": edata["cost"],
                        "type": "model",
                    },
                )

        # ── 3. Log moves (consume event, stay on same TRG node) ────────────
        for idx in range(n):
            for trg_node in trg.graph.node_indices():
                self.graph.add_edge(
                    self._node_map[(idx, trg_node)],
                    self._node_map[(idx + 1, trg_node)],
                    {
                        "firing_sequence": (),
                        "label": trace[idx].get("concept:name"),
                        "cost": 1.0,
                        "classical_cost": 1.0,
                        "type": "log",
                    },
                )

        # ── 4. Sync / execution-change moves ───────────────────────────────
        for idx in range(n):
            ev_label: str = trace[idx].get("concept:name")
            ev_enabled: set[str] = trace[idx].get("enabled") or set()

            for u, v, edata in trg_edges:
                trg_label: str | None = edata["label"]
                if trg_label == ARTIFICIAL_END_TRANSITION_LABEL:
                    continue

                esc = enabled_set_cost(ev_enabled, trg.graph[u]["enabled"])
                src = self._node_map[(idx, u)]
                dst = self._node_map[(idx + 1, v)]

                if trg_label == ev_label:
                    # Synchronous move
                    self.graph.add_edge(
                        src, dst,
                        {
                            "firing_sequence": edata["firing_sequence"],
                            "label": ev_label,
                            "cost": float(esc),
                            "classical_cost": 0.0,
                            "type": "sync",
                        },
                    )
                else:
                    # Execution-change move
                    self.graph.add_edge(
                        src, dst,
                        {
                            "firing_sequence": edata["firing_sequence"],
                            "label": ev_label,
                            "cost": float(1.0 + esc),
                            "classical_cost": 3.0,
                            "type": "change",
                        },
                    )

    # ── Query helpers ────────────────────────────────────────────────────────

    def get_optimal_alignment_cost(self, ignore_translucent: bool = False) -> float:
        weight_key = "classical_cost" if ignore_translucent else "cost"
        return rx.dijkstra_shortest_path_lengths(
            self.graph,
            self._initial_idx,
            lambda e: float(e[weight_key]),
            goal=self._final_idx,
        )[self._final_idx]

    def get_optimal_alignment(self, ignore_translucent: bool = False) -> AlignmentResult:
        weight_key = "classical_cost" if ignore_translucent else "cost"

        paths = rx.dijkstra_shortest_paths(
            self.graph,
            self._initial_idx,
            target=self._final_idx,
            weight_fn=lambda e: float(e[weight_key]),
        )
        path: list[int] = paths[self._final_idx]  # ordered list of rx node indices

        alignment: list = []
        translucent_alignment: list = []
        move_cost: list[float] = []
        cost = 0.0
        trace_idx = 0
        n_sync = n_log = n_model = n_silent = 0
        n_enabled_change = n_execution_change = n_execution_enabled_change = 0

        for u_idx, v_idx in zip(path[:-1], path[1:]):
            # For parallel edges pick the cheapest one (mirrors nx MultiDiGraph behaviour)
            edge_data = min(
                self.graph.get_all_edge_data(u_idx, v_idx),
                key=lambda e: float(e.get(weight_key, 1.0)),
            )

            firing_sequence: tuple[str, ...] = edge_data.get("firing_sequence", ())
            label: str | None = edge_data.get("label")

            # Skip the artificial end transition (arc has zero cost, bookkeeping only)
            if firing_sequence and firing_sequence[-1] == ARTIFICIAL_END_TRANSITION_NAME:
                continue

            # ── silent sub-moves (all but the last name in firing_sequence) ──
            if firing_sequence:
                silent_count = len(firing_sequence) - 1
                if silent_count:
                    alignment.extend([(SKIP, None)] * silent_count)
                    translucent_alignment.extend([(SKIP, None)] * silent_count)
                    move_cost.extend([0.0] * silent_count)
                    n_silent += silent_count

            model_side = (
                self.transition_labels[firing_sequence[-1]] if firing_sequence else SKIP
            )
            log_side = label if label else SKIP
            alignment.append((log_side, model_side))

            node_enabled: set[str] = self.graph[u_idx]["enabled"]

            if label:
                translucent_alignment.append((
                    (label, self.trace[trace_idx].get("enabled") or set()),
                    (model_side, node_enabled),
                ))
            else:
                translucent_alignment.append(((SKIP, set()), (model_side, node_enabled)))

            step_cost = float(edge_data.get(weight_key, 0.0))
            cost += step_cost
            move_cost.append(step_cost)

            move_type: str = edge_data.get("type", "")
            if move_type == "sync":
                trace_ev_enabled = self.trace[trace_idx].get("enabled") or set()
                if trace_ev_enabled == node_enabled:
                    n_sync += 1
                else:
                    n_enabled_change += 1
                trace_idx += 1
            elif move_type == "log":
                n_log += 1
                trace_idx += 1
            elif move_type == "model":
                n_model += 1
            elif move_type == "change":
                trace_ev_enabled = self.trace[trace_idx].get("enabled") or set()
                if trace_ev_enabled == node_enabled:
                    n_execution_change += 1
                else:
                    n_execution_enabled_change += 1
                trace_idx += 1

        return {
            "alignment": alignment,
            "cost": cost,
            "bwc": self.best_worst_cost,
            "visited_states": self.graph.num_nodes(),
            "queued_states": self.graph.num_nodes(),
            "traversed_arcs": self.graph.num_edges(),
            "lp_solved": 0,
            "fitness": 1.0 - cost / self.best_worst_cost if self.best_worst_cost else 0.0,
            "translucent_alignment": translucent_alignment,
            "move_cost": move_cost,
            "n_sync": n_sync,
            "n_log": n_log,
            "n_model": n_model,
            "n_silent": n_silent,
            "n_enabled_change": n_enabled_change,
            "n_execution_change": n_execution_change,
            "n_execution_enabled_change": n_execution_enabled_change,
        }