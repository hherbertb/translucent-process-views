import networkx as nx


def construct_alignment_prefix_automaton(aligned_log: list) -> nx.DiGraph:
    # Create a directed graph
    prefix_automaton = nx.DiGraph()

    # Special initial node with an empty prefix
    initial_node = ''
    prefix_automaton.add_node(initial_node)

    for i, lst in enumerate(aligned_log):
        current_prefix = initial_node

        # Special treatment for first real prefix
        first_prefix = current_prefix + lst[0][0][1]
        prefix_automaton.add_edge(initial_node, first_prefix, id=lst[0][0][1], activity=lst[0][1][1])

        # Iterate through each tuple in the current list
        for tpl in lst:
            if tpl[1][1] is not None:
                # Do not consider tau transitions since they do not happen in the log
                current_prefix += tpl[0][1]  # Add the entire ID to the current prefix

                # Add a node for the current prefix if it doesn't exist
                if not prefix_automaton.has_node(current_prefix):
                    prefix_automaton.add_node(current_prefix)

                # Add an edge with 'id' and 'activity' attributes
                if len(current_prefix) > len(tpl[0][1]):
                    prev_prefix = current_prefix[:-len(tpl[0][1])]
                    edge_attributes = {'id': tpl[0][1], 'activity': tpl[1][1]}
                    if not prefix_automaton.has_edge(prev_prefix, current_prefix):
                        prefix_automaton.add_edge(prev_prefix, current_prefix, **edge_attributes)
    return prefix_automaton


def add_enabled_activities_to_each_node(graph: nx.DiGraph) -> nx.DiGraph:
    for node in graph.nodes:
        outgoing_edges = graph.out_edges(node, data=True)
        activities_set = set(edge[2]['activity'] for edge in outgoing_edges)
        graph.nodes[node]['outgoing_activities'] = activities_set
    return graph


class AlignmentPrefixAutomaton:
    def __init__(self, alignment_list: list):
        self.alignment_prefix_automaton_without_node_information = construct_alignment_prefix_automaton(alignment_list)
        self.alignment_prefix_automaton = add_enabled_activities_to_each_node(self.alignment_prefix_automaton_without_node_information)
