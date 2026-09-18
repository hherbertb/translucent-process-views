from copy import deepcopy
from typing import Optional

from pm4py import PetriNet, Marking
from pm4py.objects.log.obj import Trace, Event, EventLog
from pm4py.objects.petri_net.utils.align_utils import SKIP
from pm4py.objects.petri_net.utils.petri_utils import add_place, add_transition, add_arc_from_to, place_set_as_marking

ARTIFICIAL_END_TRANSITION_NAME = "END"
ARTIFICIAL_END_TRANSITION_LABEL = "END"
ARTIFICIAL_END_PLACE_NAME = "FINAL"


def create_translucent_trace(translucent_events: list[tuple[str, set[str]]], name: Optional[str] = None) -> Trace:
    trace = Trace()
    if name is not None:
        trace.attributes["concept:name"] = name
    for translucent_event in translucent_events:
        event = Event()
        event["concept:name"] = translucent_event[0]
        event["enabled"] = translucent_event[1]
        trace.append(event)
    return trace


def add_artificial_end_transition(accepting_petri_net: tuple[PetriNet, Marking, Marking]) -> tuple[PetriNet, Marking, Marking]:
    accepting_petri_net = deepcopy(accepting_petri_net)
    artificial_end_transition = add_transition(accepting_petri_net[0], name=ARTIFICIAL_END_TRANSITION_NAME, label=ARTIFICIAL_END_TRANSITION_LABEL)
    for place in accepting_petri_net[2]:
        add_arc_from_to(place, artificial_end_transition, accepting_petri_net[0])
    artificial_final_place = add_place(accepting_petri_net[0], name=ARTIFICIAL_END_PLACE_NAME)
    add_arc_from_to(artificial_end_transition, artificial_final_place, accepting_petri_net[0])
    return accepting_petri_net[0], accepting_petri_net[1], place_set_as_marking([artificial_final_place])


def get_translucent_trace_variants(event_log: EventLog
                                   ) -> dict[tuple[tuple[str, frozenset[str]], ...], tuple[Trace, list[int]]]:
    variants: dict[tuple[tuple[str, frozenset[str]], ...], tuple[Trace, list[int]]] = {}
    for idx, trace in enumerate(event_log):
        variant = tuple((event["concept:name"], frozenset(event["enabled"])) for event in trace)
        if variant not in variants:
            variants[variant] = (trace, [idx])
        else:
            variants[variant][1].append(idx)
    return variants

"""
def draw_chevron(ax, x, y,
                 translucent_move: tuple[str | tuple[str, set[str]], None | str | tuple[str, set[str]]],
                 width: float = 1.,
                 height: float = 1.,
                 ) -> None:
    width2 = width / 2
    height2 = height / 2
    log_activity, log_enabled = translucent_move[0] if isinstance(translucent_move[0], tuple) else (translucent_move[0], None)
    model_activity, model_enabled = translucent_move[1] if isinstance(translucent_move[1], tuple) else (translucent_move[1], None)
    color = 'lightgreen' if log_activity == model_activity and log_enabled == model_enabled else\
        'lightgrey' if log_activity == SKIP and model_activity is None else\
        'orange' if log_activity == SKIP else\
        'lightblue' if model_activity is SKIP else\
        'lightcoral' if log_activity != model_activity else\
        'lightpink' if log_enabled != model_enabled else 'black'

    # Draw the upper half (log representation)
    chevron_upper = patches.Polygon(
        [(x, y), (x + width2, y), (x + width2 - height2 / 2, y + height2), (x - width2, y + height2), (x - width2 + height2 / 2, y)],
        closed=True, edgecolor='black', facecolor=color
    )
    ax.add_patch(chevron_upper)
    ax.text(x, y + height2 / 2, f"{log_activity}\n{log_enabled}", ha='center', va='center', fontsize=8)

    # Draw the lower half (model representation)
    chevron_lower = patches.Polygon(
        [(x, y), (x + width2, y), (x + width2 - height2 / 2, y - height2), (x - width2, y - height2), (x - width2 + height2 / 2, y)],
        closed=True, edgecolor='black', facecolor=color
    )
    ax.add_patch(chevron_lower)
    ax.text(x, y - height2 / 2, f"{model_activity}\n{model_enabled}", ha='center', va='center', fontsize=8)


def visualize_translucent_alignment(translucent_alignment: list[tuple[str | tuple[str, set[str]], None | str | tuple[str, set[str]]]], overlap: float = 0., scale: float = 1.) -> None:
    fig, ax = plt.subplots(figsize=(scale * len(translucent_alignment) * (1. - overlap) * 5, 5))
    ax.set_xlim(-1, scale * len(translucent_alignment) * (1. - overlap))
    ax.set_ylim(-1, 1)
    ax.axis('off')

    for i, move in enumerate(translucent_alignment):
        draw_chevron(ax, scale * i * (1. - overlap), 0, move, scale)

    plt.show()
"""