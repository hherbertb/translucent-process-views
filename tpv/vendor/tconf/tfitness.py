from .trg_rx import TranslucentReachabilityGraph
from .futils import get_translucent_trace_variants
from .talign import align
import networkx as nx

def calculate_log_fitness(log, petri_net, initial_marking, final_marking):
    """Calculate fitness based on translucent alignments."""
    trg = TranslucentReachabilityGraph((petri_net, initial_marking, final_marking))
    sum_cost = 0
    sum_bwc = 0
    for trace in log:
        for event in trace:
            event["enabled"] = {ea.strip() for ea in str(event["enabled_activities"]).split(",")}
    variants = get_translucent_trace_variants(log)
    variant_counter = 0
    number_of_variants = len(variants)
    for variant in variants:
        print(f"Calculating translucent fitness for variant {variant_counter+1}/{number_of_variants}")
        translucent_alignment = align(variants[variant][0], trg)
        sum_cost += translucent_alignment["cost"] * len(variants[variant][1])
        sum_bwc += translucent_alignment["bwc"] * len(variants[variant][1])
        variant_counter += 1
        
    log_fitness = float(sum_cost) / float(sum_bwc) if sum_bwc > 0 else 0
    log_fitness = 1.0 - log_fitness
    return log_fitness