"""Synthetic task-mining translucent logs.

Models the paper's Sect. 5 setting: translucent event data recorded in a user
interface, where each event's *enabled activities* are the UI actions clickable
on screen at that moment, and the hidden context is the **user's role** -- not
visible in a screenshot and possibly redacted.

Scenario: a helpdesk ticket screen.

    open_ticket -> read_history -> add_note -> [request_info]* -> DECISION -> close

Everyone sees ``read_history``, ``add_note`` and ``resolve`` in the triage menu;
``escalate`` and ``approve_refund`` are on screen only for a **supervisor**;
``request_info`` only appears for an **agent** and only when ``rework=True``.

Within a role the trace shape is fixed -- the only free choice is *which*
decision a supervisor clicks -- so the local choice set at every position is
constant per role and ``kappa`` yields exactly one identifier per role.  Two
cases with the same executed sequence still land in different process views when
one was handled by a supervisor, because the enabled sets differ.
"""

from __future__ import annotations

import random
from typing import Dict, List, Set, Tuple

from tpv.log.demo import perturb_enabled, realised_noise_rate
from tpv.log.types import TranslucentLog, TranslucentTrace

HELPDESK_ACTIONS = (
    "open_ticket",
    "read_history",
    "add_note",
    "request_info",
    "escalate",
    "approve_refund",
    "resolve",
    "close",
)
_UNIVERSE = frozenset(HELPDESK_ACTIONS)
ROLES = ("agent", "supervisor")


def _triage_menu(role: str, rework: bool) -> Set[str]:
    menu = {"read_history", "add_note", "resolve"}
    if role == "agent" and rework:
        menu.add("request_info")
    if role == "supervisor":
        menu |= {"escalate", "approve_refund"}
    return menu


def helpdesk_screen_map(rework: bool = False) -> Dict[str, Dict[str, Set[str]]]:
    """Ground-truth screen map ``state -> role -> enabled actions`` for the
    task-mining page's action x screen-state grid."""
    return {
        "start": {r: {"open_ticket"} for r in ROLES},
        "triage": {r: _triage_menu(r, rework) for r in ROLES},
        "wrap": {r: {"close"} for r in ROLES},
    }


def _trace(role: str, rnd: random.Random, rework: bool) -> TranslucentTrace:
    triage = frozenset(_triage_menu(role, rework))
    events: List[Tuple[str, frozenset]] = [
        ("open_ticket", frozenset({"open_ticket"})),
        ("read_history", triage),
        ("add_note", triage),
    ]
    if role == "agent" and rework:
        events.append(("request_info", triage))
    if role == "supervisor":
        decision = rnd.choice(["resolve", "escalate", "approve_refund"])
    else:
        decision = "resolve"
    events.append((decision, triage))
    events.append(("close", frozenset({"close"})))
    return tuple(events)


def _shared_trace(role: str, rework: bool) -> TranslucentTrace:
    """The path both roles produce (supervisor picks ``resolve``) -> one classical
    variant that appears in both views."""
    triage = frozenset(_triage_menu(role, rework))
    ev: List[Tuple[str, frozenset]] = [
        ("open_ticket", frozenset({"open_ticket"})),
        ("read_history", triage),
        ("add_note", triage),
    ]
    if role == "agent" and rework:
        ev.append(("request_info", triage))
    ev.append(("resolve", triage))
    ev.append(("close", frozenset({"close"})))
    return tuple(ev)


def task_mining_helpdesk(
    n_agent: int = 60,
    n_supervisor: int = 40,
    seed: int = 7,
    noise: float = 0.0,
    rework: bool = False,
) -> Tuple[TranslucentLog, Dict[str, str]]:
    """Build the synthetic helpdesk task-mining log.

    Returns the merged translucent log (role dropped) and a ``case_id -> role``
    ground-truth map.
    """
    rnd = random.Random(seed)
    entries: List[Tuple[TranslucentTrace, str]] = []
    ground_truth: Dict[str, str] = {}
    cid = 0
    for role, n in (("agent", n_agent), ("supervisor", n_supervisor)):
        for i in range(n):
            trace = _shared_trace(role, rework) if i % 4 == 0 else _trace(role, rnd, rework)
            trace = perturb_enabled(trace, rnd, noise, _UNIVERSE)
            case_id = f"case-{cid}"
            entries.append((trace, case_id))
            ground_truth[case_id] = role
            cid += 1
    rnd.shuffle(entries)
    name = "task-mining-helpdesk" + ("-rework" if rework else "")
    return TranslucentLog.from_traces(entries, name=name), ground_truth


# --------------------------------------------------------------------------- #
# Scenario-based case study: an IT service-desk desktop workflow (paper Sect. 5.4)
# --------------------------------------------------------------------------- #
# Base flow (UI actions across screens):
#   open -> triage{categorize, set_priority} -> diagnosis{check_kb, run_diag, remote}
#        -> ACTION xor(apply_fix, request_info [, escalate|approve])
#        -> CLOSE xor(resolve, close_noaction [, force_close]) -> log_time, notify
# Four hidden roles differ in: which blocks run in parallel vs. sequence, which
# steps are skipped, and which gated actions are on screen.  Each role has a
# fixed trace skeleton (only the executed choices vary, enabled sets are constant
# per position) so kappa yields exactly one identifier per role.
_SD_ROLES = ("agent", "senior", "specialist", "supervisor")
_SD_ACTIONS = (
    "open", "categorize", "set_priority", "check_kb", "run_diag", "remote",
    "apply_fix", "request_info", "escalate", "approve", "force_close",
    "resolve", "close_noaction", "log_time", "notify",
)
_SD_UNIVERSE = frozenset(_SD_ACTIONS)

#: per role: triage ordering, diagnosis activity set, gated ACTION options, CLOSE options
_SD_MODES: Dict[str, dict] = {
    "agent":      dict(triage="seq", diag=("check_kb",),
                       gated_action=(), close=("resolve",)),
    "senior":     dict(triage="par", diag=("check_kb", "run_diag", "remote"),
                       gated_action=("escalate",), close=("resolve", "close_noaction")),
    "specialist": dict(triage="skip", diag=("run_diag", "remote"),
                       gated_action=("escalate",), close=()),
    "supervisor": dict(triage="par", diag=("check_kb",),
                       gated_action=("approve",),
                       close=("resolve", "close_noaction", "force_close")),
}


def servicedesk_screen_map() -> Dict[str, Dict[str, Set[str]]]:
    """Ground-truth screen map ``screen -> role -> enabled actions`` for the
    service-desk desktop app (documentation artefact; the figure and a test use it)."""
    return {
        "intake":    {r: {"open"} for r in _SD_ROLES},
        "triage":    {r: (set() if _SD_MODES[r]["triage"] == "skip"
                          else {"categorize", "set_priority"}) for r in _SD_ROLES},
        "diagnosis": {r: set(_SD_MODES[r]["diag"]) for r in _SD_ROLES},
        "action":    {r: {"apply_fix", "request_info"} | set(_SD_MODES[r]["gated_action"])
                      for r in _SD_ROLES},
        "close":     {r: set(_SD_MODES[r]["close"]) for r in _SD_ROLES},
        "wrap":      {r: {"log_time", "notify"} for r in _SD_ROLES},
    }


def _seq_or_par(acts, mode: str, rnd: random.Random) -> List[Tuple[str, frozenset]]:
    """Events for an ordered block of activities.  ``seq`` -> singleton enabled
    sets in the given order; ``par`` -> random interleaving, each event's enabled
    set = every still-pending activity; ``skip`` -> no events."""
    acts = list(acts)
    if mode == "skip" or not acts:
        return []
    if mode == "seq" or len(acts) == 1:
        return [(a, frozenset({a})) for a in acts]
    order = acts[:]
    rnd.shuffle(order)
    pending = acts[:]
    out: List[Tuple[str, frozenset]] = []
    for a in order:
        out.append((a, frozenset(pending)))
        pending.remove(a)
    return out


def _sd_trace(role: str, rnd: random.Random) -> TranslucentTrace:
    m = _SD_MODES[role]
    ev: List[Tuple[str, frozenset]] = [("open", frozenset({"open"}))]
    ev += _seq_or_par(("categorize", "set_priority"), m["triage"], rnd)
    ev += _seq_or_par(m["diag"], "par", rnd)
    action_menu = frozenset({"apply_fix", "request_info"} | set(m["gated_action"]))
    # sorted, not tuple(): a frozenset of strings iterates in hash order, which
    # changes between Python processes, so the same seed drew different actions
    ev.append((rnd.choice(sorted(action_menu)), action_menu))
    if m["close"]:
        close_menu = frozenset(m["close"])
        ev.append((rnd.choice(tuple(m["close"])), close_menu))
    ev.append(("log_time", frozenset({"log_time"})))
    ev.append(("notify", frozenset({"notify"})))
    return tuple(ev)


def _sd_shared_trace(role: str, rnd: random.Random) -> TranslucentTrace:
    """The path both an agent and a supervisor can produce
    (``open, categorize, set_priority, check_kb, apply_fix, resolve, log_time, notify``)
    -> one classical variant that lands in two process views because the enabled
    sets differ."""
    m = _SD_MODES[role]
    ev: List[Tuple[str, frozenset]] = [("open", frozenset({"open"}))]
    if m["triage"] == "seq":
        ev += [("categorize", frozenset({"categorize"})),
               ("set_priority", frozenset({"set_priority"}))]
    else:
        ev += [("categorize", frozenset({"categorize", "set_priority"})),
               ("set_priority", frozenset({"set_priority"}))]
    ev.append(("check_kb", frozenset({"check_kb"})))
    action_menu = frozenset({"apply_fix", "request_info"} | set(m["gated_action"]))
    ev.append(("apply_fix", action_menu))
    ev.append(("resolve", frozenset(m["close"] or ("resolve",))))
    ev.append(("log_time", frozenset({"log_time"})))
    ev.append(("notify", frozenset({"notify"})))
    return tuple(ev)


def task_mining_servicedesk(
    n_per_role=None, seed: int = 1, noise: float = 0.0,
    noise_mode: str = "balanced",
):
    """Synthetic IT service-desk task-mining log with four hidden roles.

    ``n_per_role`` is an int (same count per role) or a ``role -> count`` dict;
    default 250 each (1000 cases).  Returns ``(TranslucentLog, gt, attrs)`` where
    ``gt`` maps case id -> role and ``attrs`` maps case id -> the standard
    clean/noisy attribute dict.

    ``noise`` is the per-event probability that one enabled activity is added or
    dropped, standing in for screenshot mis-detection; the executed activity is
    never touched.  ``noise_mode`` selects the add/drop mix -- ``"balanced"`` or
    ``"activitygen"``, the latter skewed towards spurious additions to match
    measured GUI-element detection (see :data:`tpv.log.demo._NOISE_MODES`).

    Also returns the realised corruption rate on ``log.noise_report``: the mix
    is data-dependent (an event whose enabled set is just its executed activity
    has nothing to drop), so the applied rate is worth reporting rather than
    assuming.
    """
    from tpv.log.synth import make_attributes  # lazy: synth imports this module

    if n_per_role is None:
        n_per_role = {r: 250 for r in _SD_ROLES}
    elif isinstance(n_per_role, int):
        n_per_role = {r: n_per_role for r in _SD_ROLES}

    rnd = random.Random(seed)
    arnd = random.Random(seed + 991)
    entries: List[Tuple[TranslucentTrace, str]] = []
    gt: Dict[str, str] = {}
    attrs: Dict[str, dict] = {}
    cid = 0
    n_changed = n_events = n_added = n_dropped = 0
    for role in _SD_ROLES:
        for i in range(n_per_role[role]):
            if i % 5 == 0 and role in ("agent", "supervisor"):
                trace = _sd_shared_trace(role, rnd)
            else:
                trace = _sd_trace(role, rnd)
            clean = trace
            trace = perturb_enabled(trace, rnd, noise, _SD_UNIVERSE,
                                    mode=noise_mode)
            ch, tot = realised_noise_rate(clean, trace)
            n_changed += ch
            n_events += tot
            for (_, a), (_, b) in zip(clean, trace):
                if len(b) > len(a):
                    n_added += 1
                elif len(b) < len(a):
                    n_dropped += 1
            c = f"case-{cid}"
            cid += 1
            entries.append((trace, c))
            gt[c] = role
            attrs[c] = make_attributes(role, arnd)
    rnd.shuffle(entries)
    log = TranslucentLog.from_traces(entries, name="servicedesk")
    log.noise_report = {
        "requested": noise,
        "mode": noise_mode,
        "realised": (n_changed / n_events) if n_events else 0.0,
        "n_added": n_added,
        "n_dropped": n_dropped,
        "n_events": n_events,
    }
    return log, gt, attrs


__all__ = [
    "HELPDESK_ACTIONS",
    "ROLES",
    "helpdesk_screen_map",
    "task_mining_helpdesk",
    "task_mining_servicedesk",
    "servicedesk_screen_map",
    "_SD_ROLES",
]
