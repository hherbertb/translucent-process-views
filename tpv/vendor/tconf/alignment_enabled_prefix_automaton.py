import networkx as nx
from pm4py.objects.log.obj import EventLog
import pm4py
from pm4py.algo.conformance.alignments.petri_net.variants import state_equation_a_star as star
from pm4py.algo.conformance.alignments.petri_net import algorithm as alignment


def edge_with_activity_exists(graph: nx.MultiDiGraph, source, target, activity):
    edges_between_nodes = graph.edges(source, target, keys=True)
    for edge in edges_between_nodes:
        if graph.edges[edge[0], edge[1], edge[2]]['activity'] == activity:
            return True
    return False


def construct_automaton(log: EventLog, net, im, fm, alignments, enabled_activities_attribute_name="enabled_activities",
                        enabled_activities_seperator=",") -> nx.MultiDiGraph:
    prefix_automaton = nx.MultiDiGraph()
    initial_node = ''
    prefix_automaton.add_node(initial_node)

    # sink node is needed for enabled activities in an event, but not executed
    sink_node = "sink_enabled"
    prefix_automaton.add_node(sink_node)
    """
    variants = pm4py.statistics.variants.log.get.get_variants(log) 
    variant_log = EventLog(attributes=log.attributes, extensions=log.extensions, classifiers=log.classifiers,
                           omni_present=log.omni_present, properties=log.properties)
    for variant in variants:
        variant_log.append(variants[variant][0])
    parameters = {star.Parameters.PARAM_ALIGNMENT_RESULT_IS_SYNC_PROD_AWARE: True}
    """
    for i, trace in enumerate(log):
        #alignment_result = alignment.apply(trace, net, im, fm, parameters=parameters)
        trace_alignment = alignments[i]["alignment"] #(trace, model)
        # Remove tau transitions Elias: and model skips from the alignment
        trace_alignment = [el for el in trace_alignment if el[1][1] is not None and el[1][1] != '>>']
        # Reset current prefix
        current_prefix = initial_node
        # Elias: Project the trace onto the model alignment
        trace = project_trace_on_model_alignment(trace, alignments[i]["alignment"])
        if len(trace_alignment) == 0: # If the alignment is empty, after removing model skips and taus: continue
            continue
        # Special treatment for first real prefix
        first_prefix = current_prefix + trace_alignment[0][0][1]
        prefix_automaton.add_edge(initial_node, first_prefix, id=trace_alignment[0][0][1],
                                    activity=trace_alignment[0][1][1])
        offset = 0
        #num_trace_skips = 0
        #for e in trace_alignment:
        #    if e[1][0] == '>>':
        #        num_trace_skips += 1
        #for j, event in enumerate(trace):
        for j in range(len(trace_alignment)):
            #enabled_activities = event[enabled_activities_attribute_name].split(enabled_activities_seperator)
            if trace_alignment[j][1][0] == '>>':
                offset += 1
                enabled_activities = {trace_alignment[j][1][1]}  # Only excecuted activity
            else:
                enabled_activities = trace[j-offset][enabled_activities_attribute_name].split(enabled_activities_seperator)
                enabled_activities = [el.strip() for el in enabled_activities]
                enabled_activities = set(enabled_activities)

            current_prefix += trace_alignment[j][0][1]
            # Add a node for the current prefix if it doesn't exist
            if not prefix_automaton.has_node(current_prefix):
                prefix_automaton.add_node(current_prefix)

            prev_prefix = current_prefix[:-len(trace_alignment[j][0][1])]
            # Add an edge with 'id' and 'activity' attributes
            if len(current_prefix) > len(trace_alignment[j][0][1]):
                edge_attributes = {'id': trace_alignment[j][0][1], 'activity': trace_alignment[j][1][1]}
                #if not edge_with_activity_exists(prefix_automaton, prev_prefix, current_prefix, trace_alignment[j][1][1]):
                prefix_automaton.add_edge(prev_prefix, current_prefix, **edge_attributes)
            used_activity = trace_alignment[j][1][1]
            enabled_activities.remove(used_activity)
            for activity in enabled_activities:
                edge_attributes = {'activity': activity}
                prefix_automaton.add_edge(prev_prefix, sink_node, **edge_attributes)
    return prefix_automaton


def remove_wrong_sink_arcs(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    edges_to_remove = []
    sink_node = "sink_enabled"
    edges = graph.edges
    # Iterate over nodes in the graph
    for node in graph.nodes():
        # Check if the node has outgoing edges
        if graph.out_degree(node) > 0:
            # Get the list of outgoing edges for the current node
            outgoing_edges = list(graph.out_edges(node, keys=True))
            executed_activities = set()
            for edge in outgoing_edges:
                if not edge[1] == sink_node:
                    executed_activities.add(edges[edge[:3]]['activity'])
            for edge in outgoing_edges:
                if edge[1] == sink_node:
                    if edges[edge[:3]]["activity"] in executed_activities:
                        edges_to_remove.append((edge[0], edge[1], edge[2]))
    for edge in edges_to_remove:
        graph.remove_edge(edge[0], edge[1], edge[2])
    return graph


def add_enabled_information_to_nodes(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    edges = graph.edges
    sink_node = "sink_enabled"
    # Iterate over nodes in the graph
    for node in graph.nodes():
        # Check if the node has outgoing edges
        if graph.out_degree(node) > 0:
            # Get the list of outgoing edges for the current node
            outgoing_edges = list(graph.out_edges(node, keys=True))
            executed_activities = set()
            enabled_activities = set()
            for edge in outgoing_edges:
                if not edge[1] == sink_node:
                    executed_activities.add(edges[edge[:3]]["activity"])
                enabled_activities.add(edges[edge[:3]]["activity"])
            graph.nodes[node]["enabled_executed_activities"] = executed_activities
            graph.nodes[node]["enabled_activities"] = enabled_activities
    return graph


def get_automaton(log: EventLog, net, im, fm, alignments) -> nx.MultiDiGraph:
    return add_enabled_information_to_nodes(remove_wrong_sink_arcs(construct_automaton(log, net, im, fm, alignments)))

def project_trace_on_model_alignment(trace, trace_alignment): # Elias: Should now be right
    # Only keeps events that have a matching move in the model alignment
    i = 0
    projected_trace = []
    for step in trace_alignment:
        if step[1][1] is not None and step[1][1] != '>>' and step[1][0] != '>>':
            projected_trace.append(trace[i])
            i += 1
        else:
            if step[1][1] == '>>':
                i += 1
    return projected_trace


class AlignmentEnabledPrefixAutomaton:
    def __init__(self, log: EventLog, net, im, fm, alignments):
        self.alignment_enabled_prefix_automaton = get_automaton(log, net, im, fm, alignments)
