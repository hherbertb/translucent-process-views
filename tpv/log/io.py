"""Reading and writing translucent event logs.

A translucent event carries its enabled activities in a single event attribute
(default key ``enabled_activities``) as a separator-joined string, matching the
convention of the translucent-activity-relationships miner.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Optional

import pandas as pd
import pm4py
from pm4py.objects.log.obj import Event, EventLog, Trace

from tpv.log.types import TranslucentLog, TranslucentTrace, pi_act, pi_en

_ENABLED_KEY_CANDIDATES = (
    "enabled_activities",
    "enabled",
    "en",
    "translucent:enabled",
    "enabledActivities",
)
DEFAULT_ENABLED_KEY = "enabled_activities"
DEFAULT_SEPARATOR = ","


def detect_enabled_key(columns: Iterable[str]) -> Optional[str]:
    cols = set(columns)
    for cand in _ENABLED_KEY_CANDIDATES:
        if cand in cols:
            return cand
    return None


def _split_enabled(value, separator: str) -> frozenset:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return frozenset()
    if isinstance(value, (list, set, frozenset, tuple)):
        return frozenset(str(v).strip() for v in value if str(v).strip())
    return frozenset(
        part.strip() for part in str(value).split(separator) if part.strip()
    )


def from_event_log(
    event_log: EventLog,
    enabled_key: str = DEFAULT_ENABLED_KEY,
    separator: str = DEFAULT_SEPARATOR,
    name: str = "translucent-log",
) -> TranslucentLog:
    """Convert a pm4py :class:`EventLog` into a :class:`TranslucentLog`."""
    entries = []
    for idx, trace in enumerate(event_log):
        case_id = str(trace.attributes.get("concept:name", idx))
        events = []
        for event in trace:
            act = event["concept:name"]
            enabled = _split_enabled(event.get(enabled_key), separator)
            if act not in enabled:
                enabled = enabled | {act}
            events.append((act, enabled))
        entries.append((tuple(events), case_id))
    return TranslucentLog.from_traces(entries, name=name)


def load_xes(
    path: str,
    enabled_key: str = DEFAULT_ENABLED_KEY,
    separator: str = DEFAULT_SEPARATOR,
) -> TranslucentLog:
    event_log = pm4py.read_xes(path, return_legacy_log_object=True)
    return from_event_log(
        event_log, enabled_key=enabled_key, separator=separator, name=_basename(path)
    )


def load_csv(
    path: str,
    enabled_key: Optional[str] = None,
    separator: str = DEFAULT_SEPARATOR,
    case_key: str = "case:concept:name",
    activity_key: str = "concept:name",
    timestamp_key: str = "time:timestamp",
) -> TranslucentLog:
    df = pd.read_csv(path)
    return from_dataframe(
        df,
        enabled_key=enabled_key,
        separator=separator,
        case_key=case_key,
        activity_key=activity_key,
        timestamp_key=timestamp_key,
        name=_basename(path),
    )


def from_dataframe(
    df: pd.DataFrame,
    enabled_key: Optional[str] = None,
    separator: str = DEFAULT_SEPARATOR,
    case_key: str = "case:concept:name",
    activity_key: str = "concept:name",
    timestamp_key: str = "time:timestamp",
    name: str = "translucent-log",
) -> TranslucentLog:
    """Build a translucent log from a flat event table."""
    df = df.copy()
    if case_key not in df.columns and "case:concept:name" in df.columns:
        case_key = "case:concept:name"
    if enabled_key is None:
        enabled_key = detect_enabled_key(df.columns) or DEFAULT_ENABLED_KEY
    if timestamp_key in df.columns:
        df = df.sort_values([case_key, timestamp_key], kind="stable")
    entries = []
    for case_id, group in df.groupby(case_key, sort=False):
        events = []
        for _, row in group.iterrows():
            act = str(row[activity_key])
            enabled = _split_enabled(row.get(enabled_key), separator)
            if act not in enabled:
                enabled = enabled | {act}
            events.append((act, enabled))
        entries.append((tuple(events), str(case_id)))
    return TranslucentLog.from_traces(entries, name=name)


def to_event_log(
    log: TranslucentLog,
    enabled_key: str = DEFAULT_ENABLED_KEY,
    separator: str = DEFAULT_SEPARATOR,
) -> EventLog:
    """Materialise a :class:`TranslucentLog` as a pm4py :class:`EventLog`.

    Enabled sets are written back as a ``separator``-joined string so the result
    round-trips through :func:`from_event_log`.
    """
    import datetime as _dt

    out = EventLog()
    base = _dt.datetime(2000, 1, 1)
    for trace, count in log.variants.items():
        case_ids = log.case_ids.get(trace) or []
        for k in range(count):
            case_id = case_ids[k] if k < len(case_ids) else f"{log.name}-{id(trace)}-{k}"
            pm_trace = Trace(attributes={"concept:name": str(case_id)})
            for pos, (act, enabled) in enumerate(trace):
                pm_trace.append(
                    Event(
                        {
                            "concept:name": act,
                            enabled_key: (separator + " ").join(sorted(enabled)),
                            "time:timestamp": base + _dt.timedelta(minutes=pos),
                        }
                    )
                )
            out.append(pm_trace)
    return out


def export_xes(
    log: TranslucentLog,
    path: str,
    enabled_key: str = DEFAULT_ENABLED_KEY,
    separator: str = DEFAULT_SEPARATOR,
) -> None:
    pm4py.write_xes(to_event_log(log, enabled_key=enabled_key, separator=separator), path)


def _basename(path: str) -> str:
    import os

    return os.path.splitext(os.path.basename(path))[0] or "translucent-log"


__all__ = [
    "DEFAULT_ENABLED_KEY",
    "DEFAULT_SEPARATOR",
    "detect_enabled_key",
    "from_event_log",
    "from_dataframe",
    "load_xes",
    "load_csv",
    "to_event_log",
    "export_xes",
]
