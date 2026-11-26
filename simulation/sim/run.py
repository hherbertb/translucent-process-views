"""Run N simulated procurement cases and write a translucent event log.

    python -m sim.run --scenario purchase_to_pay --cases 40 --seed 42
    python -m sim.run --scenario mixed --cases 60 --seed 42 --concurrency 6
    python -m sim.run --scenario tickets --cases 5 --seed 1 --headed --think-scale 2   # watch it

Scenarios: purchase_to_pay, order_to_cash, tickets, mixed (cases of all three interleaved).

Output goes to output/<run name>/ : events.csv, events.xes, variants.csv,
summary.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config, stats
from .bootstrap import bootstrap
from .browser import RoleSession
from .core import Backend
from .rpc import Odoo, db_service
from .scenarios import CASES, SCENARIOS

COLUMNS = [
    "seq", "timestamp", "case_id", "scenario", "activity", "event_type", "outcome", "error",
    "role", "user", "doc_model", "doc_id", "doc_name", "doc_state", "doc_state_after", "case_state", "case_state_after",
    "enabled_activities", "enabled_activities_gui", "enabled_activities_backend",
    "enabled_activities_backend_case", "sets_agree", "only_gui", "only_backend",
    "executed_in_gui", "executed_in_backend", "gui_other_actions",
    "active_app", "active_window_title", "browser_url",
    "element_name", "element_type", "element_id", "element_rect", "element_source", "x", "y",
    "dom_path", "element_xpath", "dom_html", "seed",
]


def join(s) -> str:
    return ", ".join(sorted(s))


class Sim:
    def __init__(self, seed: int, think_scale: float, out_dir: Path):
        self.seed = seed
        self.think_scale = think_scale
        self.out_dir = out_dir
        self.admin = Odoo(config.ADMIN_LOGIN, config.ADMIN_PASSWORD)
        users = {r: Odoo(s["login"], s["password"]) for r, s in config.ROLES.items()}
        self.backend = Backend(self.admin, users)
        self.sessions: dict[str, RoleSession] = {}
        self.seq = 0
        out_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(out_dir / "events.csv", "w", newline="", encoding="utf-8")
        self._csv = csv.DictWriter(self._fh, fieldnames=COLUMNS)
        self._csv.writeheader()

    def log(self, ev: dict) -> None:
        self.seq += 1
        gui, backend, case_set = ev.pop("gui"), ev.pop("backend"), ev.pop("backend_case")
        act = ev["activity"]
        row = dict(ev)
        row.update({
            "seq": self.seq, "seed": self.seed,
            # The column the existing miner reads: the GUI-derived set. The
            # executed activity is added if the derivation missed it; that is
            # counted in `executed_in_gui` and must stay at zero misses.
            "enabled_activities": join(gui | {act}),
            "enabled_activities_gui": join(gui),
            "enabled_activities_backend": join(backend),
            "enabled_activities_backend_case": join(case_set),
            "sets_agree": int(gui == backend),
            "only_gui": join(gui - backend),
            "only_backend": join(backend - gui),
            "executed_in_gui": int(act in gui),
            "executed_in_backend": int(act in backend),
        })
        self._csv.writerow(row)
        self._fh.flush()
        flag = "" if row["outcome"] == "ok" else "  [rejected]"
        print(f"{self.seq:5d} {row['case_id']} {row['role']:<10} {act}{flag}", flush=True)

    def close(self) -> None:
        self._fh.close()


def case_factory(scenario: str, seed: int):
    """Which scenario case number `i` belongs to. In a mixed run the choice
    is drawn per case index, independent of everything else."""
    if scenario != "mixed":
        return lambda i: CASES[scenario]
    names = sorted(CASES)
    return lambda i: CASES[random.Random(f"{seed}/mix/{i}").choice(names)]


def run(scenario: str, cases: int, seed: int, concurrency: int, headed: bool, think_scale: float,
        out_dir: Path, slow_mo: int) -> dict:
    if config.DB not in db_service().list():
        bootstrap()
    sim = Sim(seed, think_scale, out_dir)
    make = case_factory(scenario, seed)
    wanted = sorted(CASES) if scenario == "mixed" else [scenario]
    roles = [r for r in config.ROLES if any(r in SCENARIOS[n].roles for n in wanted)]
    sched = random.Random(f"{seed}/scheduler")
    aborted: list[dict] = []
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, slow_mo=slow_mo)
        for role in roles:
            sim.sessions[role] = RoleSession(browser, role, slow_mo_wait=0.4 if headed else 0.0)
            sim.sessions[role].login()

        pending = list(range(cases))
        active: list[tuple[Case, object]] = []
        while pending or active:
            while pending and len(active) < concurrency:
                i = pending.pop(0)
                c = make(i)(sim, i)
                active.append((c, c.run()))
            entry = sched.choice(active)
            case, gen = entry
            try:
                next(gen)
            except StopIteration:
                active.remove(entry)
            except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
                active.remove(entry)
                err_dir = out_dir / "errors"
                err_dir.mkdir(exist_ok=True)
                for role, s in sim.sessions.items():
                    try:
                        s.page.screenshot(path=str(err_dir / f"{case.case_id}_{role}.png"))
                        if s.modal_open():
                            s.page.keyboard.press("Escape")
                    except Exception as e2:  # noqa: BLE001 - recorded with the abort
                        sim.backend.caught.append(("cleanup", role, "screenshot", str(e2)[:300]))
                aborted.append({"case_id": case.case_id, "scenario": case.sc.name,
                                "error": f"{type(exc).__name__}: {exc}"[:500],
                                "traceback": traceback.format_exc()[-1500:]})
                print(f"!! {case.case_id} aborted: {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
        for s in sim.sessions.values():
            s.close()
        browser.close()
    sim.close()

    summary = stats.summarise(out_dir / "events.csv")
    summary.update({"scenario": scenario, "seed": seed, "cases_requested": cases,
                    "db_uuid": sim.admin.call("ir.config_parameter", "get_param", "database.uuid"), "concurrency": concurrency,
                    "think_scale": think_scale, "aborted_cases": aborted,
                    "duration_s": round(time.time() - t0, 1)})
    caught = [dict(zip(("kind", "role", "call", "message"), c)) for c in sim.backend.caught]
    (out_dir / "exceptions.json").write_text(json.dumps(caught, indent=1), encoding="utf-8")
    summary["caught_exceptions"] = {k: sum(c["kind"] == k for c in caught)
                                    for k in ("denied", "unexpected", "cleanup")}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    stats.write_variants(out_dir / "events.csv", out_dir / "variants.csv")
    stats.write_xes(out_dir / "events.csv", out_dir / "events.xes")
    stats.write_miner_csv(out_dir / "events.csv", out_dir / "miner.csv")
    stats.print_summary(summary)
    print(f"\nlog: {out_dir / 'events.csv'}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="purchase_to_pay",
                    choices=sorted(CASES) + ["mixed"], help="which process to simulate")
    ap.add_argument("--cases", type=int, default=30, help="number of procurement cases")
    ap.add_argument("--seed", type=int, default=42, help="same seed -> same variants")
    ap.add_argument("--concurrency", type=int, default=4, help="cases open at the same time")
    ap.add_argument("--headed", action="store_true", help="show the browser windows")
    ap.add_argument("--slow-mo", type=int, default=0, help="ms delay per browser operation (headed viewing)")
    ap.add_argument("--think-scale", type=float, default=1.0,
                    help="multiplier for agent think time (mean 0.4 s per action; 0 = none)")
    ap.add_argument("--out", type=Path, default=None, help="output directory")
    ap.add_argument("--url", default=None, help="Odoo base URL (default http://127.0.0.1:8069)")
    a = ap.parse_args()
    if a.url:
        config.URL = a.url.rstrip("/")
    out = a.out or Path("output") / f"{a.scenario}_seed{a.seed}_n{a.cases}_c{a.concurrency}"
    run(a.scenario, a.cases, a.seed, a.concurrency, a.headed, a.think_scale, out, a.slow_mo)


if __name__ == "__main__":
    main()
