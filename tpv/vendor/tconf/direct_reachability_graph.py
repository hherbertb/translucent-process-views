import networkx as nx
from networkx import MultiDiGraph
from automata.fa.dfa import DFA
from automata.fa.nfa import NFA
import copy

# NFA -> DFA subset construction below is worst-case exponential; bail before it
# on a graph large enough to make that intractable (see reachability_graph.py).
_MAX_NFA_NODES = 2_000
"""
from pyvis.network import Network
import numpy as np

def visualize_graph(graph, filename="debug_graph.html"):
    # Create a fresh, empty graph for the visualization
    clean_graph = nx.MultiDiGraph()
    
    # 1. Sanitize Nodes
    for node, data in graph.nodes(data=True):
        # Convert node names to strings if they are arrays or complex objects
        clean_node = str(node) if isinstance(node, (np.ndarray, list, dict)) else node
        # Add to clean graph, adding a title for hover-over tooltips
        clean_graph.add_node(str(clean_node), title=str(data))
        
    # 2. Sanitize Edges
    for u, v, key, data in graph.edges(keys=True, data=True):
        clean_u = str(u) if isinstance(u, (np.ndarray, list, dict)) else str(u)
        clean_v = str(v) if isinstance(v, (np.ndarray, list, dict)) else str(v)
        
        # Safely extract your custom transition label
        transition = data.get("transition")
        if transition is None or transition.label is None:
            edge_label = "tau"
        else:
            edge_label = str(transition.label)
            
        weight = data.get("weight", "")
        display_label = f"{edge_label} (w: {weight})" if weight else edge_label

        # Add the edge with only basic JSON-safe string attributes
        clean_graph.add_edge(clean_u, clean_v, label=display_label)

    # 3. Render the sanitized graph
    net = Network(directed=True, notebook=False)
    # Pyvis layout tweak to handle MultiDiGraph parallel edges better
    net.set_options("""
   # var options = {
    #  "edges": {
     #   "smooth": {
      #    "type": "dynamic",
       #   "forceDirection": "none"
        #}
      #}
    #}
    #""")
    #net.from_nx(clean_graph)
    #net.show(filename, notebook=False)

def find_final_nodes(graph: MultiDiGraph):
    nodes_numbers_of_edges = {}
    nodes_to_work_on = set()
    nodes_to_work_on.add(1)
    while len(nodes_to_work_on)>0:
        current_node = nodes_to_work_on.pop()
        if current_node not in nodes_numbers_of_edges:
            nodes_numbers_of_edges[current_node] = 0
            edges_of_node = list(graph.in_edges(current_node))
            for el in edges_of_node:
                temp = graph.edges(el[0], el[1], keys=True)
                for edge in temp:
                    if edge[0] != current_node and edge[1] == current_node:
                        nodes_numbers_of_edges[current_node] += 1
                        if graph.edges[edge[0], edge[1], edge[2]]["transition"].label is None:
                            nodes_numbers_of_edges[current_node] -= 1
                            nodes_to_work_on.add(edge[0])
    target_nodes = set()
    for node in nodes_numbers_of_edges:
        if nodes_numbers_of_edges[node] > 0:
            target_nodes.add(node)
    return target_nodes

# Elias: If a tau loop exists in the original petri net, this will not terminate. As a hack I set a limit to the number of iterations.
# If it is reached, the remaining tau edges are removed and we pray that no trace is long enough to be affected by this.
# Of course this is not ideal


def remove_tau_add_successor_edges(graph: MultiDiGraph) -> MultiDiGraph:
    still_tau = True
    no_of_iterations = 0
    max_iterations = len(graph.nodes) + 1 # Should be a valid upper bound
    edges_to_consider = list(graph.edges)
    while still_tau and no_of_iterations < max_iterations:
        print(f"Iteration {no_of_iterations} of maximum {max_iterations} removing tau edges.")
        no_of_iterations += 1
        still_tau = False
        for edge in edges_to_consider:
            if graph.edges[edge[0], edge[1], edge[2]]["transition"].label is None:
                edges_to_add = set()
                still_tau = True
                successors = list(graph.successors(edge[1]))
                for successor in successors:
                    temp = graph.edges(edge[1], successor, keys=True)
                    for edges_between_target_and_successor in temp:
                        if edges_between_target_and_successor[1] == successor:
                            edges_to_add.add((edge[0],
                                             successor,
                                             graph.edges[edge[1], successor, edges_between_target_and_successor[2]]["transition"],
                                            graph.edges[edge[1], successor, edges_between_target_and_successor[2]][
                                               "weight"] + 1))
                for source, target, transition, weight in edges_to_add:
                    graph.add_edge(source,target, transition=transition, weight=weight)
                graph.remove_edge(edge[0], edge[1], edge[2])
                edges_to_consider = list(graph.edges)
    if no_of_iterations >= max_iterations:
        print("Warning: Maximum iterations reached while removing tau edges. Remaining tau edges will be removed without adding successor edges.")
        for edge in list(graph.edges):
            if graph.edges[edge[0], edge[1], edge[2]]["transition"].label is None:
                graph.remove_edge(edge[0], edge[1], edge[2])
    return graph

def remove_tau_add_successor_edges_optimized(graph: MultiDiGraph) -> MultiDiGraph:
    # 1. Identify tau edges and non-tau edges
    tau_edges = []
    non_tau_edges = []

    for u, v, k, data in graph.edges(keys=True, data=True):
        if data["transition"].label is None:
            tau_edges.append((u, v))
        else:
            non_tau_edges.append((u, v, k, data))

    # 2. Build a graph of only tau transitions for reachability analysis
    # We use a DiGraph to compute shortest paths (BFS)
    tau_graph = nx.DiGraph()
    tau_graph.add_nodes_from(graph.nodes())
    tau_graph.add_edges_from(tau_edges)

    # 3. Pre-compute observable edges per node for fast lookup
    observable_out_edges = {}
    for u, v, k, data in non_tau_edges:
        if u not in observable_out_edges:
            observable_out_edges[u] = []
        observable_out_edges[u].append((v, data))

    edges_to_add = []

    # 4. For each node, find all reachable nodes via tau edges (transitive closure)
    for u in graph.nodes():
        # BFS to find reachable nodes and distances
        visited = {u: 0}
        queue = [u]

        while queue:
            curr = queue.pop(0)
            dist = visited[curr]

            # If we reached a node (other than start) that has observable edges,
            # add connections from start 'u' to the targets of those edges.
            if dist > 0 and curr in observable_out_edges:
                for target, data in observable_out_edges[curr]:
                    # Weight is distance in tau-graph + weight of the observable edge
                    new_weight = data["weight"] + dist
                    edges_to_add.append((u, target, data["transition"], new_weight))

            if curr in tau_graph:
                for neighbor in tau_graph[curr]:
                    if neighbor not in visited:
                        visited[neighbor] = dist + 1
                        queue.append(neighbor)

    # 5. Remove all tau edges
    edges_to_remove = []
    for u, v, k, data in graph.edges(keys=True, data=True):
        if data["transition"].label is None:
            edges_to_remove.append((u, v, k))

    graph.remove_edges_from(edges_to_remove)

    # 6. Add the new shortcut edges
    for u, v, transition, weight in edges_to_add:
        graph.add_edge(u, v, transition=transition, weight=weight)

    return graph

def remove_tau_add_successor_edges_optimized_old(graph: MultiDiGraph) -> MultiDiGraph:
    # OPTIMIZATION 1: Find all initial tau edges just ONCE
    tau_edges = [
        (u, v, k) for u, v, k, data in graph.edges(keys=True, data=True)
        if data["transition"].label is None
    ]
    
    max_iterations = len(graph.nodes) + 1
    iteration = 0
    
    # Process level-by-level to respect max_iterations
    while tau_edges and iteration < max_iterations:
        print(f"Iteration {iteration} of maximum {max_iterations} removing tau edges.")
        iteration += 1
        new_tau_edges = []
        
        for u, v, k in tau_edges:
            # FIX: Ensure edge still exists (it might have been removed in a previous step)
            if not graph.has_edge(u, v, key=k):
                continue
                
            # OPTIMIZATION 2: Fast lookup of all outgoing edges and their data
            # .out_edges(v) yields tuples of (source, target, key, data_dict)
            for _, successor, out_k, out_data in list(graph.out_edges(v, keys=True, data=True)):
                
                new_transition = out_data["transition"]
                new_weight = out_data.get("weight", 0) + 1
                
                # Add the new bypass edge
                new_k = graph.add_edge(u, successor, transition=new_transition, weight=new_weight)
                
                # If the bypassed edge is ALSO a tau edge, queue it for the next iteration
                if new_transition.label is None:
                    new_tau_edges.append((u, successor, new_k))
            
            # Remove the original tau edge
            graph.remove_edge(u, v, key=k)
            
        # Move to the next batch of newly discovered tau edges
        tau_edges = new_tau_edges
        
    if tau_edges:
        print("Warning: Maximum iterations reached. Remaining tau edges will be removed without adding successor edges.")
        for u, v, k in tau_edges:
            if graph.has_edge(u, v, key=k):
                graph.remove_edge(u, v, key=k)
                
    return graph

def construct_dfa(graph: MultiDiGraph, reachability_graph: MultiDiGraph):
    """
    :param graph:
    :return: dfa
    """

    final_nodes = find_final_nodes(reachability_graph)

    initial_state = 0
    input_symbols = set()
    transitions = {}
    for edge in graph.edges:
        transition = graph.edges[edge[0], edge[1], edge[2]]["transition"].name
        if transition not in input_symbols:
            input_symbols.add(transition)
        if edge[0] not in transitions:
            transitions[edge[0]] = {}
        if transition not in transitions[edge[0]]:
            transitions[edge[0]][transition] = set()
        transitions[edge[0]][transition].add(edge[1])
    nodes_in_drg = set(list(graph.nodes))
    if len(nodes_in_drg) > _MAX_NFA_NODES:
        raise MemoryError(
            f"DRG has {len(nodes_in_drg)} nodes (> {_MAX_NFA_NODES}); NFA->DFA "
            "subset construction intractable, model too loose for translucent "
            "precision"
        )
    for node in final_nodes:
        if node not in nodes_in_drg:
            final_nodes.remove(node)
    nfa = NFA(states=nodes_in_drg,
              input_symbols=input_symbols,
              transitions=transitions,
              initial_state=initial_state,
              final_states=final_nodes)
    dfa = DFA.from_nfa(nfa, retain_names=True)
    resulting_graph = nx.MultiDiGraph()
    resulting_graph.add_nodes_from(dfa.states)
    for start_state in dfa.transitions:
        for transition in dfa.transitions[start_state]:
            resulting_graph.add_edge(start_state, dfa.transitions[start_state][transition], transition=transition)
    #for start_state, transition in dfa.transitions.items():
    #    for end_state in transition.values():
    #        name = get_key_from_value(transition, end_state)
    #        resulting_graph.add_edge(start_state, end_state, transition=name)
    return resulting_graph


def remove_nodes_with_no_ingoing_arcs(graph: MultiDiGraph) -> MultiDiGraph:
    # Identify nodes with no incoming edges
    nodes_to_remove = [node for node, in_degree in graph.in_degree() if in_degree == 0 and node != 0]
    # Remove nodes with no incoming edges
    graph.remove_nodes_from(nodes_to_remove)
    return graph


def add_enabled_activities_to_nodes_drg(graph: MultiDiGraph) -> MultiDiGraph:
    nodes = graph.nodes()
    for node in nodes:
        activities = set()
        successors = list(graph.successors(node))
        for successor in successors:
            edges_between_nodes = graph.edges(node, successor, keys=True)
            edges_between_nodes = [element for element in edges_between_nodes if element[1] == successor]
            for edge in edges_between_nodes:
                transition = graph.edges[edge[:3]]['transition']
                activities.add(transition.label)
        graph.nodes[node]["enabled_activities"] = activities
    return graph


def add_enabled_activities_to_nodes_dfa(dfa: MultiDiGraph, net) -> MultiDiGraph:
    def get_label(transition_name):
        for el in net.transitions:
            if el.name == transition_name:
                return el.label

    nodes = dfa.nodes()
    for node in nodes:
        activities = set()
        successors = list(dfa.successors(node))
        for successor in successors:
            edges_between_nodes = dfa.edges(node, successor, keys=True)
            edges_between_nodes = [element for element in edges_between_nodes if element[1] == successor]
            for edge in edges_between_nodes:
                transition = dfa.edges[edge[:3]]['transition']
                activities.add(get_label(transition))
        dfa.nodes[node]["enabled_activities"] = activities
    return dfa


class DirectReachabilityGraph:
    def __init__(self, r_g):
        self.reachability_graph = r_g.reachability_graph
        self.direct_reachability_graph = self.transform_rg_to_drg()
        self.dfa = add_enabled_activities_to_nodes_dfa(construct_dfa(self.direct_reachability_graph, self.reachability_graph), r_g.net)

    def transform_rg_to_drg(self):
        temp = copy.deepcopy(self.reachability_graph)
        temp = remove_tau_add_successor_edges_optimized(temp) # TODO: Change this back to unoptimized if does not work!
        temp = remove_nodes_with_no_ingoing_arcs(temp)
        return add_enabled_activities_to_nodes_drg(temp)
