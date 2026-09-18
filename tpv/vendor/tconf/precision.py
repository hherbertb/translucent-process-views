from .reachability_graph import ReachabilityGraph
from .direct_reachability_graph import DirectReachabilityGraph
import pm4py
import pandas as pd
import networkx as nx
from .alignment_prefix_automaton import AlignmentPrefixAutomaton
from .alignment_enabled_prefix_automaton import AlignmentEnabledPrefixAutomaton
from pm4py.objects.conversion.log import converter as log_converter
from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.algo.conformance.alignments.petri_net.variants import state_equation_a_star as star
from pm4py.algo.conformance.alignments.petri_net import algorithm as alignment
from pm4py.objects.log.obj import EventLog
from typing import Union


def get_alignments(log: EventLog, net: PetriNet, im: Marking, fm: Marking) -> list:
    parameters = {star.Parameters.PARAM_ALIGNMENT_RESULT_IS_SYNC_PROD_AWARE: True}
    # bound the A* search so a loose, highly-concurrent model cannot hang the run
    try:
        parameters[star.Parameters.PARAM_MAX_ALIGN_TIME] = 45.0
        parameters[star.Parameters.PARAM_MAX_ALIGN_TIME_TRACE] = 6.0
    except Exception:  # pragma: no cover - pm4py layout change
        pass
    alignment_result = alignment.apply(log, net, im, fm, parameters=parameters)
    #filtered_list = [t["alignment"] for t in alignment_result if t.get("fitness", None) == 1.0]
    return alignment_result


def get_node_from_transition(graph, node, transition):
    edges = graph.out_edges(node, data= True, keys=True)
    for edge in edges:
        if graph.edges[edge[0], edge[1], edge[2]]["transition"] == transition:
            return edge[1]
    return None


def compute_precision(aligned_log: list, prefix_automaton: nx.DiGraph, drg: nx.MultiDiGraph):
    fractions = []
    for trace in aligned_log:
        transition_sequence = ""
        node = frozenset({frozenset({0})})
        for event in trace:
            if event[1][1] is not None:
                number_executed = len(prefix_automaton.nodes[transition_sequence]["outgoing_activities"])
                node_of_interest = drg.nodes[node]
                temp = node_of_interest["enabled_activities"]
                number_enabled = len(temp)
                fractions.append(number_executed / number_enabled)
                transition_sequence += event[0][1]
                node = get_node_from_transition(drg, node, event[0][1])
    return sum(fractions) / len(fractions)


def compute_translucent_precision(aligned_log, prefix_enabled_automaton: nx.MultiDiGraph, rg, drg, dfa: nx.MultiDiGraph,
                                  weight_translucent=1):
    #aligned_log = [t["alignment"] for t in aligned_log if t.get("fitness", None) == 1.0] #TODO: Change this!
    aligned_log = [t["alignment"] for t in aligned_log]
    fractions = []
    for trace in aligned_log:
        transition_sequence = ""
        node = frozenset({frozenset({0})})
        for event in trace:
            if event[1][1] is not None and event[1][1] != '>>':
                """
                executed = prefix_enabled_automaton.nodes[transition_sequence]["enabled_executed_activities"]
                enabled = prefix_enabled_automaton.nodes[transition_sequence]["enabled_activities"]
                only_enabled = enabled - executed
                number_executed = len(executed) + weight_translucent * len(only_enabled)
                number_enabled = len(drg.nodes[node]["enabled_activities"])
                fractions.append(number_executed / number_enabled)
                transition_sequence += event[0][1]
                node = get_node_from_transition(drg, node, event[0][1])
                """
                log_enabled = prefix_enabled_automaton.nodes[transition_sequence]["enabled_activities"] #Elias: Non-Determinism of alignments causes issues -> use the same alignments in both steps!
                model_enabled = dfa.nodes[node]["enabled_activities"]
                nominator = log_enabled.intersection(model_enabled)
                denominator = model_enabled
                fractions.append(len(nominator)/len(denominator))
                transition_sequence += event[0][1]
                node = get_node_from_transition(dfa, node, event[0][1])
    return sum(fractions) / len(fractions)


def precision_score(log: Union[pd.DataFrame, EventLog], net: PetriNet, initial_marking: Marking,
                    final_marking: Marking):
    if isinstance(log, pd.DataFrame):
        log = log_converter.apply(log, variant=log_converter.Variants.TO_EVENT_LOG)
    alignments = get_alignments(log, net, initial_marking, final_marking)
    alignment_prefix_automaton = AlignmentPrefixAutomaton(alignments).alignment_prefix_automaton
    r_g = ReachabilityGraph(net, initial_marking, final_marking, 1)
    d_r_g = DirectReachabilityGraph(r_g).dfa
    return compute_precision(alignments, alignment_prefix_automaton, d_r_g)


def translucent_precision_score(log: Union[pd.DataFrame, EventLog], net: PetriNet, initial_marking: Marking,
                                final_marking: Marking):
    if isinstance(log, pd.DataFrame):
        log = log_converter.apply(log, variant=log_converter.Variants.TO_EVENT_LOG)
    alignments = get_alignments(log, net, initial_marking, final_marking)
    alignment_enabled_prefix_automaton = AlignmentEnabledPrefixAutomaton(log,
                                                                         net, initial_marking, final_marking, alignments).alignment_enabled_prefix_automaton
    r_g = ReachabilityGraph(net, initial_marking, final_marking, 1)
    d = DirectReachabilityGraph(r_g)
    drg = d.direct_reachability_graph
    dfa = d.dfa
    return compute_translucent_precision(alignments, alignment_enabled_prefix_automaton, r_g, drg, dfa)

def translucent_precision_score_eval_version(log: Union[pd.DataFrame, EventLog], net: PetriNet, initial_marking: Marking,
                                final_marking: Marking):
    if isinstance(log, pd.DataFrame):
        log = log_converter.apply(log, variant=log_converter.Variants.TO_EVENT_LOG)
    alignments = get_alignments(log, net, initial_marking, final_marking)
    fitness = pm4py.algo.evaluation.replay_fitness.variants.alignment_based.evaluate(alignments) ["log_fitness"]

    alignment_enabled_prefix_automaton = AlignmentEnabledPrefixAutomaton(log,
                                                                         net, initial_marking, final_marking, alignments).alignment_enabled_prefix_automaton
    r_g = ReachabilityGraph(net, initial_marking, final_marking, 1)
    d = DirectReachabilityGraph(r_g)
    drg = d.direct_reachability_graph
    dfa = d.dfa
    return compute_translucent_precision(alignments, alignment_enabled_prefix_automaton, r_g, drg, dfa), fitness
