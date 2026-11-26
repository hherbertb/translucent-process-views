"""Quality analysis of a simulation run.

    python -m sim.quality output/<run>                       # all checks except (d)
    python -m sim.quality output/<run> --repro output/<run2> # with the same-seed rerun
    python -m sim.quality output/<run> --no-db               # skip (f), Odoo not running

Writes <run>/quality.md and <run>/quality.json and exits with status 1 if a
hard check fails (2 if a check could not be run at all).

Hard checks, per scenario and, for a mixed run, over the whole log:
  a  executed activity is in the GUI enabled set (raw set, before any repair)
  b  accepted actions are in the backend set, rejected ones are not
  c  no aborted case, no unexpected exception caught anywhere, every case logged
  d  same seed gives identical traces and identical global order (needs --repro)
  e  timestamps non-decreasing per case, no duplicate events, required fields filled
  f  the log agrees with Odoo: tracked state changes in the database (chatter
     tracking values) and logged state changes match one to one, and every
     document's final state in the log equals the database
  g  every GUI/backend difference has a named cause
  h  CSV and XES load in pm4py with the expected counts; the translucent miner
     (IMts) runs on the log
Soft measures (judged good / weak / poor): variants, activity coverage,
enabled-set sizes, share of events with more than one enabled activity, role
distribution, translucent vs. plain inductive miner.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import statistics
import sys
import traceback
import warnings
from collections import Counter, defaultdict
from pathlib import Path

from .scenarios import SCENARIOS

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
MINER_FALLBACK = Path(r"C:\Users\beyel\Documents\Code\Translucent Activity Relationships"
                      r"\TranslucentActivityRelationships")
REQUIRED = ["seq", "timestamp", "case_id", "scenario", "activity", "outcome", "role", "user",
            "doc_model", "doc_id", "doc_state_after", "case_state_after", "enabled_activities",
            "enabled_activities_gui", "enabled_activities_backend", "browser_url", "dom_path",
            "element_xpath", "element_type"]
NULL_LABEL = {"user_id": "unassigned"}


def load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return sorted(csv.DictReader(fh), key=lambda r: int(r["seq"]))


def split(cell: str) -> set[str]:
    return {x for x in cell.split(", ") if x}


def label(r: dict) -> str:
    return r["activity"] + (" (rejected)" if r["outcome"] != "ok" else "")


def traces(rows) -> dict[str, tuple]:
    t = defaultdict(list)
    for r in rows:
        t[r["case_id"]].append(label(r))
    return {k: tuple(v) for k, v in t.items()}


def result(ok: bool | None, summary: str, details=None) -> dict:
    return {"status": "PASS" if ok else ("SKIPPED" if ok is None else "FAIL"),
            "summary": summary, "details": (details or [])[:40]}


# --- hard checks ------------------------------------------------------------
def check_a(rows):
    bad = [f"{r['seq']} {r['case_id']} {r['activity']}" for r in rows if r["executed_in_gui"] != "1"]
    return result(not bad, f"{len(rows) - len(bad)}/{len(rows)} events have the executed activity "
                           f"in the GUI set", bad)


def check_b(rows):
    bad = []
    for r in rows:
        inb = r["executed_in_backend"] == "1"
        if r["outcome"] == "ok" and not inb:
            bad.append(f"accepted but not in backend set: {r['seq']} {r['case_id']} {r['activity']}")
        if r["outcome"] != "ok" and inb:
            bad.append(f"rejected but in backend set: {r['seq']} {r['case_id']} {r['activity']}")
    n_rej = sum(r["outcome"] != "ok" for r in rows)
    return result(not bad, f"{len(rows) - n_rej} accepted, {n_rej} rejected; {len(bad)} violations", bad)


def check_c(rows, summary: dict, scope: str):
    det = []
    aborted = [a for a in summary.get("aborted_cases", [])
               if scope == "all" or a.get("scenario") == scope]
    det += [f"aborted {a['case_id']}: {' '.join(a['error'].split())[:200]}" for a in aborted]
    caught = summary.get("caught_exceptions")
    if caught is None:
        det.append("run has no exception record (made by an older version)")
    else:
        if caught.get("unexpected") or caught.get("cleanup"):
            det.append(f"caught exceptions: {caught}")
    rej_no_text = [r["seq"] for r in rows if r["outcome"] != "ok" and not r["error"].strip()]
    if rej_no_text:
        det.append(f"rejected events without error text: {rej_no_text}")
    if scope == "all":
        n = len({r["case_id"] for r in rows})
        if n != summary.get("cases_requested"):
            det.append(f"{summary.get('cases_requested')} cases requested, {n} in the log")
    return result(not det, f"{len(aborted)} aborted cases; caught exceptions {caught}", det)


def check_d(rows, repro_rows):
    if repro_rows is None:
        return result(None, "no --repro run given")
    ta, tb = traces(rows), traces(repro_rows)
    diff = sorted(c for c in set(ta) | set(tb) if ta.get(c) != tb.get(c))
    ga = [(r["case_id"], label(r)) for r in rows]
    gb = [(r["case_id"], label(r)) for r in repro_rows]
    det = [f"{c}: {' > '.join(ta.get(c, ()))}  ||  {' > '.join(tb.get(c, ()))}" for c in diff]
    if ga != gb:
        k = next((i for i, (x, y) in enumerate(zip(ga, gb)) if x != y), min(len(ga), len(gb)))
        det.append(f"global order differs first at position {k + 1}: "
                   f"{ga[k] if k < len(ga) else '-'} vs {gb[k] if k < len(gb) else '-'}")
    return result(not diff and ga == gb,
                  f"{len(ta)} vs {len(tb)} cases, {len(diff)} with a different trace, "
                  f"global order {'identical' if ga == gb else 'differs'}", det)


def check_e(rows):
    import datetime as dt
    det = []
    last: dict[str, dt.datetime] = {}
    for r in rows:
        t = dt.datetime.fromisoformat(r["timestamp"])
        if r["case_id"] in last and t < last[r["case_id"]]:
            det.append(f"time goes back in {r['case_id']} at seq {r['seq']}")
        last[r["case_id"]] = t
    seqs = [int(r["seq"]) for r in rows]
    if len(set(seqs)) != len(seqs):
        det.append("duplicate seq numbers")
    keys = Counter((r["case_id"], r["timestamp"], r["activity"]) for r in rows)
    det += [f"duplicate event {k}" for k, n in keys.items() if n > 1]
    for r in rows:
        empty = [c for c in REQUIRED if not str(r.get(c, "")).strip()]
        if empty:
            det.append(f"seq {r['seq']} {r['activity']}: empty {empty}")
    return result(not det, f"{len(rows)} events checked for order, duplicates and "
                           f"{len(REQUIRED)} required fields", det)


def parse_state(cell: str) -> dict:
    """'po:12=purchase;receipt:31=done' -> {('po', 12): 'purchase', ...}"""
    out = {}
    for part in filter(None, cell.split(";")):
        key, val = part.split("=", 1)
        short, rid = key.split(":")
        out[(short, int(rid))] = val
    return out


def check_f(rows, scope_names):
    """Compare the log with Odoo's own record of state changes."""
    from . import config
    from .rpc import Odoo
    admin = Odoo(config.ADMIN_LOGIN, config.ADMIN_PASSWORD)
    det, n_tracked, n_final, n_docs, n_untracked = [], 0, 0, 0, 0
    for name in scope_names:
        sc = SCENARIOS[name]
        model_of = {v: k for k, v in sc.SHORT.items()}
        srows = [r for r in rows if r["scenario"] == name]
        # logged values per (doc, part): chain of (seq, old, new) and the first value
        logged = defaultdict(list)
        first, final = {}, {}
        for r in srows:
            before, after = parse_state(r["case_state"]), parse_state(r["case_state_after"])
            for doc, val in after.items():
                parts_after = val.split("/")
                if doc not in first:
                    first[doc] = parts_after if doc not in before else before[doc].split("/")
                final[doc] = parts_after
                if doc in before:
                    for i, (o, n) in enumerate(zip(before[doc].split("/"), parts_after)):
                        if o != n:
                            logged[(doc, i)].append((int(r["seq"]), o, n))
            for doc, val in before.items():
                first.setdefault(doc, val.split("/"))
        docs_by_model = defaultdict(set)
        for (short, rid) in final:
            docs_by_model[model_of[short]].add(rid)
        for model, ids in docs_by_model.items():
            ids = sorted(ids)
            n_docs += len(ids)
            spec = sc.TRACKED[model]
            fields = [f for _, f, _ in spec]
            meta = {m["name"]: m for m in admin.search_read(
                "ir.model.fields", [("model", "=", model), ("name", "in", fields)],
                ["name", "tracking", "ttype"])}
            sel = admin.call(model, "fields_get", fields, attributes=["selection"])
            lab2key = {f: {lbl: key for key, lbl in (sel[f].get("selection") or [])} for f in fields}

            def norm(field, value):
                if meta[field]["ttype"] == "selection":
                    return lab2key[field].get(value, value)
                return value or NULL_LABEL.get(field, "")

            # tracking values, in order, per (doc id, field)
            fid = {m["id"]: m["name"] for m in meta.values()}
            msgs = admin.search_read("mail.message", [("model", "=", model), ("res_id", "in", ids),
                                                      ("tracking_value_ids", "!=", False)],
                                     ["res_id", "tracking_value_ids"], order="id")
            tv_ids = [t for m in msgs for t in m["tracking_value_ids"]]
            tvs = {t["id"]: t for t in admin.read("mail.tracking.value", tv_ids,
                                                   ["field_id", "old_value_char", "new_value_char"])}
            odoo = defaultdict(list)
            for m in msgs:
                for t in sorted(m["tracking_value_ids"]):
                    tv = tvs[t]
                    fname = fid.get(tv["field_id"][0]) if tv["field_id"] else None
                    if fname:
                        odoo[(m["res_id"], fname)].append(
                            (norm(fname, tv["old_value_char"]), norm(fname, tv["new_value_char"])))
            # current values in the database
            cur = {r["id"]: r for r in admin.read(model, ids, fields)}
            short = sc.SHORT[model]
            for rid in ids:
                doc = (short, rid)
                for idx, field, _kind in spec:
                    v = cur[rid][field]
                    if meta[field]["ttype"] == "many2one":
                        v = v[1] if v else NULL_LABEL.get(field, "")
                    db_val = str(v)
                    log_val = final[doc][idx] if idx < len(final[doc]) else None
                    n_final += 1
                    if log_val != db_val:
                        det.append(f"{model} {rid} {field}: log ends with {log_val!r}, database has {db_val!r}")
                    if not meta[field]["tracking"]:
                        continue
                    chain = odoo.get((rid, field), [])
                    n_tracked += len(chain)
                    i = 0
                    for seq, o, n in logged.get((doc, idx), []):
                        if (model, field, o, n) in sc.UNTRACKED and (i >= len(chain) or chain[i][0] != o):
                            n_untracked += 1
                            continue  # Odoo leaves no trace; the next tracked change must start at n
                        if i >= len(chain) or chain[i][0] != o:
                            det.append(f"{model} {rid} {field}: logged change {o}->{n} (seq {seq}) "
                                       f"not in Odoo's tracking at position {i + 1}: {chain}")
                            break
                        j = i
                        while j < len(chain) and chain[j][1] != n:
                            j += 1
                        if j == len(chain):
                            det.append(f"{model} {rid} {field}: logged change {o}->{n} (seq {seq}) "
                                       f"not completed in Odoo's tracking {chain[i:]}")
                            break
                        i = j + 1
                    else:
                        if i < len(chain):
                            det.append(f"{model} {rid} {field}: Odoo changes without event: {chain[i:]}")
    return result(not det, f"{n_docs} documents, {n_tracked} tracked state changes in Odoo matched, "
                           f"{n_untracked} logged changes Odoo does not track (declared), "
                           f"{n_final} final values compared", det)


def check_g(rows):
    det, causes = [], Counter()
    for r in rows:
        sc = SCENARIOS[r["scenario"]]
        for side in ("only_gui", "only_backend"):
            for act in split(r[side]):
                c = sc.explain(side, act, r)
                if c:
                    causes[(r["scenario"], c, side, act)] += 1
                else:
                    det.append(f"seq {r['seq']} {r['case_id']} {r['role']} {side}: {act} "
                               f"(doc {r['doc_model']} {r['doc_state']})")
    return result(not det, f"{sum(causes.values())} explained differences, {len(det)} unexplained",
                  det), causes


@contextlib.contextmanager
def quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield


def import_miner(paths: list[Path]):
    """Import discover_petri_net / discover_process_tree from the first copy
    that imports cleanly; return (module, path used, failures)."""
    fails = []
    for p in paths:
        for k in [k for k in sys.modules if k.startswith("translucent_discovery")]:
            del sys.modules[k]
        sys.path.insert(0, str(p))
        try:
            import importlib
            mod = importlib.import_module("translucent_discovery.translucent_inductive_miner.translucent_base")
            return mod, p, fails
        except Exception as exc:  # noqa: BLE001 - reported
            fails.append(f"{p}: {type(exc).__name__}: {exc}")
        finally:
            sys.path.remove(str(p))
    return None, None, fails


def canon(tree) -> str:
    """Order-independent string of a pm4py process tree (children of xor /
    parallel / or sorted, sequence and loop kept in order)."""
    if not tree.children:
        return tree.label if tree.label is not None else "tau"
    kids = [canon(c) for c in tree.children]
    op = str(tree.operator)
    if op in ("X", "+", "O"):
        kids = sorted(kids)
    return f"{op}({', '.join(kids)})"


def check_h(run: Path, rows, scope_names, miner_paths, n_cases_expected):
    import pandas as pd
    import pm4py
    from pm4py.objects.conversion.log import converter as lc
    det, models = [], {}
    with quiet():
        df = pd.read_csv(run / "events.csv")
        df = pm4py.format_dataframe(df, case_id="case_id", activity_key="activity", timestamp_key="timestamp")
        xes = pm4py.read_xes(str(run / "events.xes"))
        mdf = pd.read_csv(run / "miner.csv")
        mdf = pm4py.format_dataframe(mdf, case_id="case", activity_key="activity", timestamp_key="timestamp")
    for what, d in (("events.csv", df), ("events.xes", xes), ("miner.csv", mdf)):
        n_c, n_e = d["case:concept:name"].nunique(), len(d)
        if (n_c, n_e) != (n_cases_expected, len(rows)):
            det.append(f"{what}: {n_c} cases / {n_e} events, expected {n_cases_expected} / {len(rows)}")
    mod, used, fails = import_miner(miner_paths)
    det_fail = list(det)
    note = [f"miner import failed: {f}" for f in fails]
    if mod is None:
        return result(False, "translucent miner could not be imported", det + note), models, None
    params = {"translucent_variant": "IMts", "tDFG_fall_through": False}
    for name in scope_names + (["all"] if len(scope_names) > 1 else []):
        cases = {r["case_id"] for r in rows if name == "all" or r["scenario"] == name}
        sub = mdf[mdf["case:concept:name"].isin(cases)]
        try:
            with quiet():
                log = lc.apply(sub, variant=lc.Variants.TO_EVENT_LOG)
                net, im, fm = mod.discover_petri_net(log, dict(params))
                t_ts = mod.discover_process_tree(log, dict(params), 0)
                t_im = mod.discover_process_tree(log, {"translucent_variant": "IM",
                                                       "tDFG_fall_through": False}, 0)
                t_plain = pm4py.discover_process_tree_inductive(sub)
            models[name] = {
                "imts_places": len(net.places), "imts_transitions": len(net.transitions),
                "imts_visible": len([t for t in net.transitions if t.label]),
                "imts_equals_plain_im": canon(t_ts) == canon(t_plain),
                "imts_equals_miner_im": canon(t_ts) == canon(t_im),
                "imts_tree": canon(t_ts)[:600], "plain_tree": canon(t_plain)[:600],
            }
        except Exception as exc:  # noqa: BLE001 - this is the check
            det_fail.append(f"miner failed on {name}: {type(exc).__name__}: {exc}")
            det_fail.append(traceback.format_exc()[-600:])
    ok = not det_fail
    summ = (f"pm4py: CSV, XES and miner.csv load with {n_cases_expected} cases / {len(rows)} events; "
            f"IMts ran on {len(models)} log(s) using {used}")
    return result(ok, summ, det_fail + note), models, str(used)


# --- soft measures ----------------------------------------------------------
def judge(value: str, poor: bool, weak: bool) -> dict:
    return {"value": value, "judgement": "poor" if poor else ("weak" if weak else "good")}


def soft(rows, name, models):
    tr = traces(rows)
    var = Counter(tr.values())
    n = len(tr)
    top = var.most_common(1)[0][1] / n if n else 0
    ratio = len(var) / n if n else 0
    out = {"variants": judge(f"{len(var)} variants over {n} cases (ratio {ratio:.2f}); most frequent "
                             f"variant covers {top:.0%} of cases",
                             top > 0.5 or ratio >= 1.0 or len(var) < 3, top > 0.35 or ratio > 0.9)}
    scs = [SCENARIOS[name]] if name in SCENARIOS else [SCENARIOS[s] for s in sorted({r["scenario"] for r in rows})]
    vocab = {a for sc in scs for a in sc.VOCABULARY if a not in sc.NEVER_EXECUTED}
    done = {r["activity"] for r in rows}
    cov = len(done & vocab) / len(vocab)
    missing = sorted(vocab - done)
    out["activity_coverage"] = judge(f"{len(done & vocab)}/{len(vocab)} = {cov:.0%} of the executable "
                                     f"vocabulary; not executed: {missing}", cov < 0.6, cov < 0.85)
    sizes = [len(split(r["enabled_activities"])) for r in rows]
    bsizes = [len(split(r["enabled_activities_backend"])) for r in rows]
    q = statistics.quantiles(sizes, n=4) if len(sizes) > 1 else [sizes[0]] * 3
    hist = dict(sorted(Counter(sizes).items()))
    out["enabled_set_size"] = {"value": f"enabled_activities: min {min(sizes)}, quartiles {q}, max "
                                        f"{max(sizes)}, mean {statistics.mean(sizes):.2f}; backend mean "
                                        f"{statistics.mean(bsizes):.2f}; histogram {hist}",
                               "judgement": "info"}
    multi = sum(s > 1 for s in sizes) / len(sizes)
    out["multi_enabled_share"] = judge(f"{multi:.0%} of events have more than one enabled activity",
                                       multi < 0.5, multi < 0.8)
    roles = Counter(r["role"] for r in rows)
    expected = {ro for sc in scs for ro in sc.roles}
    zero = sorted(expected - set(roles))
    low = sorted(ro for ro, c in roles.items() if c / len(rows) < 0.03)
    out["roles"] = judge(f"{dict(roles.most_common())}; without events: {zero}; under 3%: {low}",
                         bool(zero), bool(low))
    m = models.get(name)
    if m:
        same = m["imts_equals_plain_im"]
        out["translucent_vs_plain"] = judge(
            f"IMts net {m['imts_places']} places / {m['imts_transitions']} transitions; process tree "
            f"{'identical to' if same else 'differs from'} plain inductive miner; "
            f"{'identical to' if m['imts_equals_miner_im'] else 'differs from'} the miner's own IM variant",
            False, same)
    return out


# --- driver -----------------------------------------------------------------
def analyse(run: Path, repro: Path | None, use_db: bool, miner_paths: list[Path]) -> dict:
    rows = load(run / "events.csv")
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    repro_rows = load(repro / "events.csv") if repro else None
    names = sorted({r["scenario"] for r in rows})
    scopes = names + (["all"] if len(names) > 1 else [])
    rep = {"run": str(run), "repro": str(repro) if repro else None, "scopes": {}}
    h, models, used = check_h(run, rows, names, miner_paths, len({r["case_id"] for r in rows}))
    rep["miner_used"] = used
    if use_db:
        try:
            f_all = {n: check_f(rows, [n]) for n in names}
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            f_all = {n: result(False, f"could not query Odoo: {type(exc).__name__}: {exc}") for n in names}
    for scope in scopes:
        sr = [r for r in rows if scope == "all" or r["scenario"] == scope]
        rr = None if repro_rows is None else [r for r in repro_rows if scope == "all" or r["scenario"] == scope]
        g, causes = check_g(sr)
        hard = {
            "a_executed_in_gui": check_a(sr),
            "b_backend_matches_outcome": check_b(sr),
            "c_no_aborts_or_hidden_errors": check_c(sr, summary, scope),
            "d_same_seed_same_log": check_d(sr, rr),
            "e_order_duplicates_fields": check_e(sr),
        }
        if not use_db:
            hard["f_log_matches_odoo"] = result(None, "skipped (--no-db)")
        elif scope == "all":
            fs = [f_all[n] for n in names]
            hard["f_log_matches_odoo"] = result(all(x["status"] == "PASS" for x in fs),
                                                "; ".join(x["summary"] for x in fs),
                                                [d for x in fs for d in x["details"]])
        else:
            hard["f_log_matches_odoo"] = f_all[scope]
        hard["g_disagreements_explained"] = g
        hard["h_pm4py_and_miner"] = h
        tr = traces(sr)
        rep["scopes"][scope] = {
            "counts": {"cases": len(tr), "events": len(sr),
                       "distinct_activities": len({r["activity"] for r in sr}),
                       "distinct_variants": len(set(tr.values())),
                       "rejected_events": sum(r["outcome"] != "ok" for r in sr),
                       "gui_backend_agreement": round(sum(r["sets_agree"] == "1" for r in sr) / len(sr), 4),
                       },
            "hard": hard,
            "causes": [{"scenario": k[0], "cause": k[1], "side": k[2], "activity": k[3], "events": v}
                       for k, v in causes.most_common()],
            "soft": soft(sr, scope, models),
        }
    rep["failed"] = sorted({f"{s}:{k}" for s, d in rep["scopes"].items()
                            for k, v in d["hard"].items() if v["status"] == "FAIL"})
    rep["poor"] = sorted({f"{s}:{k}" for s, d in rep["scopes"].items()
                          for k, v in d["soft"].items() if v.get("judgement") == "poor"})
    rep["models"] = models
    return rep


def markdown(rep: dict) -> str:
    out = [f"# Quality report: `{rep['run']}`", ""]
    out.append(f"Same-seed rerun: `{rep['repro']}`" if rep["repro"] else "Same-seed rerun: not given")
    out.append(f"Translucent miner used: `{rep['miner_used']}`")
    out.append("")
    out.append(f"**Hard checks failed:** {rep['failed'] or 'none'}  ")
    out.append(f"**Soft measures judged poor:** {rep['poor'] or 'none'}")
    for scope, d in rep["scopes"].items():
        c = d["counts"]
        out += ["", f"## {scope}", "",
                f"{c['cases']} cases, {c['events']} events, {c['distinct_activities']} activities, "
                f"{c['distinct_variants']} variants, {c['rejected_events']} rejected attempts, "
                f"GUI/backend agreement {c['gui_backend_agreement']:.1%}", "",
                "| check | status | result |", "|---|---|---|"]
        for k, v in d["hard"].items():
            out.append(f"| {k} | {v['status']} | {v['summary']} |")
        for k, v in d["hard"].items():
            if v["details"] and v["status"] != "PASS":
                out += ["", f"<details><summary>{k}: details</summary>", "", "```"]
                out += [str(x) for x in v["details"]]
                out += ["```", "</details>"]
        if d["causes"]:
            out += ["", "| GUI/backend difference | side | activity | events |", "|---|---|---|---|"]
            out += [f"| {x['cause']} | {x['side']} | {x['activity']} | {x['events']} |" for x in d["causes"]]
        out += ["", "| soft measure | judgement | value |", "|---|---|---|"]
        for k, v in d["soft"].items():
            out.append(f"| {k} | {v['judgement']} | {v['value']} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--repro", type=Path, default=None, help="run folder of the same-seed rerun")
    ap.add_argument("--no-db", action="store_true", help="skip check f (needs Odoo)")
    ap.add_argument("--miner", type=Path, action="append", default=None,
                    help="folder that contains translucent_discovery/ (repeatable, tried in order)")
    a = ap.parse_args()
    miners = a.miner or [WORKTREE_ROOT, MINER_FALLBACK]
    try:
        rep = analyse(a.run, a.repro, not a.no_db, miners)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
    (a.run / "quality.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    md = markdown(rep)
    (a.run / "quality.md").write_text(md, encoding="utf-8")
    for scope, d in rep["scopes"].items():
        print(f"[{scope}] " + ", ".join(f"{k}={v}" for k, v in d["counts"].items()))
        for k, v in d["hard"].items():
            print(f"   {v['status']:7s} {k}: {v['summary'][:150]}")
        for k, v in d["soft"].items():
            print(f"   {v['judgement']:7s} {k}: {v['value'][:150]}")
    print(f"\nfailed: {rep['failed'] or 'none'}; poor: {rep['poor'] or 'none'}")
    print(f"report: {a.run / 'quality.md'}")
    sys.exit(1 if rep["failed"] else 0)


if __name__ == "__main__":
    main()
