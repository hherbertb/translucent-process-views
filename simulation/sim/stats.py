"""Log statistics, variant comparison and XES export (standard library only).

    python -m sim.stats output/seed42_n30_c4              # print summary
    python -m sim.stats compare output/runA output/runB   # same variants per case?
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr


def load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def label(row: dict) -> str:
    """Activity label used for variants: refused attempts are kept apart."""
    return row["activity"] + (" (rejected)" if row["outcome"] != "ok" else "")


def traces(rows: list[dict]) -> dict[str, tuple[str, ...]]:
    t: dict[str, list[str]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: int(r["seq"])):
        t[r["case_id"]].append(label(r))
    return {k: tuple(v) for k, v in t.items()}


def split(cell: str) -> list[str]:
    return [x for x in cell.split(", ") if x]


def summarise(path: Path) -> dict:
    rows = load(path)
    tr = traces(rows)
    n = len(rows) or 1
    only_gui, only_backend = Counter(), Counter()
    for r in rows:
        only_gui.update(split(r["only_gui"]))
        only_backend.update(split(r["only_backend"]))
    ok = [r for r in rows if r["outcome"] == "ok"]
    rej = [r for r in rows if r["outcome"] != "ok"]
    jacc = []
    for r in rows:
        g, b = set(split(r["enabled_activities_gui"])), set(split(r["enabled_activities_backend"]))
        jacc.append(len(g & b) / len(g | b) if g | b else 1.0)
    return {
        "cases": len(tr),
        "events": len(rows),
        "distinct_activities": len({r["activity"] for r in rows}),
        "distinct_variants": len(set(tr.values())),
        "rejected_events": len(rej),
        "avg_enabled_gui": round(sum(len(split(r["enabled_activities_gui"])) for r in rows) / n, 2),
        "avg_enabled_backend": round(sum(len(split(r["enabled_activities_backend"])) for r in rows) / n, 2),
        "set_agreement_rate": round(sum(r["sets_agree"] == "1" for r in rows) / n, 4),
        "mean_jaccard": round(sum(jacc) / n, 4),
        "events_with_disagreement": sum(r["sets_agree"] != "1" for r in rows),
        "disagreement_only_gui": dict(only_gui.most_common()),
        "disagreement_only_backend": dict(only_backend.most_common()),
        # invariants
        "executed_missing_from_gui": sum(r["executed_in_gui"] != "1" for r in rows),
        "accepted_missing_from_backend": sum(r["executed_in_backend"] != "1" for r in ok),
        "rejected_but_in_backend": sum(r["executed_in_backend"] == "1" for r in rej),
        "activity_counts": dict(Counter(label(r) for r in rows).most_common()),
    }


def print_summary(s: dict) -> None:
    print("\n=== summary ===")
    for k in ("cases", "events", "distinct_activities", "distinct_variants", "rejected_events",
              "avg_enabled_gui", "avg_enabled_backend", "set_agreement_rate", "mean_jaccard",
              "events_with_disagreement", "executed_missing_from_gui",
              "accepted_missing_from_backend", "rejected_but_in_backend"):
        print(f"{k:32s} {s[k]}")
    print("shown in GUI but not allowed by backend:", s["disagreement_only_gui"])
    print("allowed by backend but not shown in GUI:", s["disagreement_only_backend"])
    if s.get("aborted_cases"):
        for c in s["aborted_cases"]:
            print("ABORTED:", c["case_id"], " ".join(c["error"].split())[:300])


def write_variants(events: Path, out: Path) -> None:
    tr = traces(load(events))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "length", "variant"])
        for cid in sorted(tr):
            w.writerow([cid, len(tr[cid]), " > ".join(tr[cid])])


XES_KEYS = ["role", "user", "scenario", "outcome", "doc_model", "doc_name", "doc_state", "doc_state_after",
            "enabled_activities", "enabled_activities_gui", "enabled_activities_backend",
            "enabled_activities_backend_case", "browser_url", "element_name", "dom_path"]


def write_xes(events: Path, out: Path) -> None:
    rows = sorted(load(events), key=lambda r: int(r["seq"]))
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[r["case_id"]].append(r)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<log xes.version="1.0" xes.features="">\n')
        fh.write('  <extension name="Concept" prefix="concept" uri="http://www.xes-standard.org/concept.xesext"/>\n')
        fh.write('  <extension name="Time" prefix="time" uri="http://www.xes-standard.org/time.xesext"/>\n')
        fh.write('  <extension name="Organizational" prefix="org" uri="http://www.xes-standard.org/org.xesext"/>\n')
        for cid in sorted(by_case):
            fh.write(f'  <trace>\n    <string key="concept:name" value={quoteattr(cid)}/>\n')
            for r in by_case[cid]:
                fh.write("    <event>\n")
                fh.write(f'      <string key="concept:name" value={quoteattr(r["activity"])}/>\n')
                fh.write(f'      <date key="time:timestamp" value={quoteattr(r["timestamp"])}/>\n')
                fh.write(f'      <string key="org:resource" value={quoteattr(r["user"])}/>\n')
                fh.write(f'      <string key="org:role" value={quoteattr(r["role"])}/>\n')
                for k in XES_KEYS[2:]:
                    fh.write(f'      <string key="{k}" value={quoteattr(r[k])}/>\n')
                fh.write("    </event>\n")
            fh.write("  </trace>\n")
        fh.write("</log>\n")


def write_miner_csv(events: Path, out: Path) -> None:
    """Minimal input for the translucent miners: case, activity, timestamp,
    enabled_activities (the columns their evaluation scripts read with
    pm4py.format_dataframe(case_id='case', ...)). Timestamps in UTC, without
    offset, strictly increasing within a case."""
    import datetime as dt
    rows = sorted(load(events), key=lambda r: int(r["seq"]))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "activity", "timestamp", "enabled_activities"])
        for r in rows:
            t = dt.datetime.fromisoformat(r["timestamp"]).astimezone(dt.timezone.utc)
            w.writerow([r["case_id"], r["activity"], t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        r["enabled_activities"]])


def compare(a: Path, b: Path) -> bool:
    ta, tb = traces(load(a / "events.csv")), traces(load(b / "events.csv"))
    diff = sorted(c for c in set(ta) | set(tb) if ta.get(c) != tb.get(c))
    print(f"cases: {len(ta)} vs {len(tb)}; distinct variants: {len(set(ta.values()))} vs "
          f"{len(set(tb.values()))}; cases with a different trace: {len(diff)}")
    for c in diff[:10]:
        print(f"  {c}\n    A: {' > '.join(ta.get(c, ()))}\n    B: {' > '.join(tb.get(c, ()))}")
    return not diff


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "compare" and len(args) == 3:
        sys.exit(0 if compare(Path(args[1]), Path(args[2])) else 1)
    if len(args) != 1:
        sys.exit(__doc__)
    s = summarise(Path(args[0]) / "events.csv")
    print_summary(s)
    print(json.dumps(s["activity_counts"], indent=2))


if __name__ == "__main__":
    main()
