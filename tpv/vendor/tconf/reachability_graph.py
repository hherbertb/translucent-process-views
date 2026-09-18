import numpy as np
import networkx as nx

# guard against an unbounded reachability graph on a loose, highly-concurrent
# model (see the matching note in trg_rx.py): raise instead of exhausting memory
# kept small on purpose: the reachability graph feeds an NFA -> DFA subset
# construction (direct_reachability_graph.construct_dfa) that is worst-case
# exponential, so even a few thousand RG nodes can grind for hours.  Legitimate
# per-view sub-logs stay well under 100 nodes; the loose mixed/noisy models that
# blow up jump to the thousands, so this cleanly separates them.
_MAX_RG_NODES = 2_500


def requirement_firing(net):
    """
    Computes how many tokens in which place are needed for a transition to fire.
    :param net: PM4Py Petri Net object
    :return: dictionary, whereby the keys are the transition, the values are a np.array which only marks where
    tokens are consumed for the respective transition.
    {t1: [-1 0 0]}
    """
    place_list = list(net.places)
    transition_dict = {}
    for transition in net.transitions:
        temp = np.zeros(len(place_list))
        for arc in transition.in_arcs:
            temp[place_list.index(arc.source)] -= arc.weight
        transition_dict[transition] = temp
    return transition_dict


def transition_firing_information(incidence_matrix, net):
    """
    We transform the information that is available in the incidence in a more readable form. This means that we
    construct a dictionary, whereby a key is the name of a transition
    :param incidence_matrix: Incidence Matrix of a Petri Net
    :param net: Petri Net
    :return: Dictionary
    {t1: [-1 +1 0]}
    """
    firing_dict = {}
    i = 0
    transitions = list(net.transitions)
    while i < len(transitions):
        firing_dict[transitions[i]] = incidence_matrix[:, i]
        i += 1
    return firing_dict


def get_post_firing_marking(marking, firing_dict, requirement_dict):
    """
    We compute all possible markings after all enabled transition have fired.
    :param marking: current marking
    :param firing_dict: Dictionary which provides us with the firing information whereby the key is the transition
            {t1:
    :param requirement_dict: Dict, whereby keys are transitions, key np.array that marks from which places the
    amount of tokens is needed to fire
    :return: List of tuples, whereby the first element is the new marking, the second element is the transition that
    was used to reach the new marking.
    """
    firing_result = []
    for transition, requirement in requirement_dict.items():
        if all(np.greater_equal(marking, requirement.copy() * -1)):
            firing_result.append((marking + firing_dict[transition], transition))
    return firing_result


def convert_marking(net, marking):
    """
    Since we are working with numpy arrays as representation of marking, we need no transform the initial marking
    to such a representation.
    :param net: Petri net
    :param marking: Marking which is returned from discovery algorithms of PM4Py
    :return: numpy array that represents the initial marking
    {p1: 1, p2: 0, p3:0}
    """
    places = list(net.places)
    conv = np.zeros(len(places))
    i = 0
    while i < len(places):
        if places[i] in marking:
            conv[i] = marking[places[i]]
        i += 1
    return conv


class ReachabilityGraph:
    def __init__(self, net, i_m, f_m, weight_tau=0):
        self.net = net
        self.i_m = i_m
        self.f_m = f_m
        self.reachability_graph = self.get_graph(weight_tau)

    def compute_incidence_matrix(self):
        """
        We compute the incidence matrix of a Petri Net. It provides us with the firing requirements of a transition and
        its outcome. The matrix has rows equals to the number of places and columns equals to the number of transition.
        As a result, the columns represent the firing information for each transition.
        :return: Numpy Matrix representing the incidence matrix.
            t1
        p1  -1
        p2  +1
        p3   0
        -1: token is consumed from place, +1: token is added to place
        """
        incidence_matrix = np.zeros((len(self.net.places), len(self.net.transitions)))
        transitions = list(self.net.transitions)
        places = list(self.net.places)
        i = 0
        while i < len(transitions):
            transition = transitions[i]
            for ingoing_arc in transition.in_arcs:
                # A transition consumes a token from its input places. Therefore, we have to subtract 1.
                incidence_matrix[places.index(ingoing_arc.source), i] -= ingoing_arc.weight
            for outgoing_arc in transition.out_arcs:
                # A transition produces one token for each of its "destination" places. Therefore, we have to add 1.
                incidence_matrix[places.index(outgoing_arc.target), i] += outgoing_arc.weight
            i += 1
        return incidence_matrix

    def construct_reachability_graph(self, initial_marking, final_marking, weight_tau):
        """
        We construct a reachability graph. Important to note is that we only expand nodes/marking, which can be reached
        in at most n non-tau transitions.
        :param final_marking: final marking of Petri net, already converted into a np.array representation
        :param initial_marking: initial marking of Petri Net, already converted into a np.array representation
        :param weight_tau: Weight of tau transitions
        :return: Networkx Multi-Directed Graph object
        """
        # compute incidence matrix
        incidence_matrix = self.compute_incidence_matrix()

        # compute requirement_dict
        requirement_dict = requirement_firing(self.net)

        # compute firing dict
        firing_dict = transition_firing_information(incidence_matrix, self.net)

        # output graph is a MulitDiGraph to represent self-loops and parallel edges
        graph = nx.MultiDiGraph()
        # the initial marking is node 0. We add the marking as data to the node
        j = 0
        graph.add_node(j, marking=initial_marking)
        # the reference table reveals the node-number a particular marking has
        reference_table = {np.array2string(initial_marking): j}
        j += 1
        # the final marking is node 1. We add the marking as data to the node
        graph.add_node(j, marking=final_marking)
        reference_table = {np.array2string(final_marking): j}
        j += 1


        # our set of nodes which has to be extended in the reachability graph
        work = set()
        work.add(0)

        while len(work) > 0:
            if graph.number_of_nodes() > _MAX_RG_NODES:
                raise MemoryError(
                    f"reachability graph exceeded {_MAX_RG_NODES} nodes; "
                    "model too loose for translucent conformance"
                )
            # select a random marking and remove it from the work set
            mark = work.pop()
            # a list of marking that are reachable by firing transition which are currently available
            reachable_markings = get_post_firing_marking(graph.nodes[mark]['marking'], firing_dict,
                                                         requirement_dict)
            for marking in reachable_markings:
                if np.array2string(marking[0]) not in reference_table:
                    # the first element of marking represent the numpy representation of that marking, the second the
                    # transition that was taken
                    # If the marking is not in the graph yet, we add it
                    reference_table[np.array2string(marking[0])] = j
                    graph.add_node(j, marking=marking[0])
                    if marking[1].label is None:
                        # If the transition that fires is tau transition, we need an edge of weight 0, normally.
                        # However, this can be parameterized.
                        graph.add_edge(mark, j, transition=marking[1], weight=weight_tau)
                    else:
                        # If a non-tau transition fires, we need a weight of 1
                        graph.add_edge(mark, j, transition=marking[1], weight=1)
                    work.add(j)
                    j += 1
                else:
                    # The marking is in the graph. However, we have to add the edge.
                    observerable_marking = reference_table[np.array2string(marking[0])]
                    if marking[1].label is None:
                        graph.add_edge(mark, observerable_marking, transition=marking[1], weight=weight_tau)
                    else:
                        graph.add_edge(mark, observerable_marking, transition=marking[1], weight=1)
        return graph

    def get_graph(self, weight_tau):
        initial_marking = convert_marking(self.net, self.i_m)
        final_marking = convert_marking(self.net, self.f_m)
        return self.construct_reachability_graph(initial_marking, final_marking, weight_tau)
