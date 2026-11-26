"""Case viewer: turn a run's events.csv into one static HTML page.

    python -m sim.viewer output/<run>            -> output/<run>/cases.html

One section per case, one row per event: who did what on which document, the
state before and after, and the GUI and backend enabled sets side by side.
Activities only one of the two sets contains are highlighted, the executed
activity is underlined, rejected attempts are marked. "open" links the
document in Odoo (http://127.0.0.1:8069, log in as the row's user to see the
same buttons the agent saw; the document will be in its *current* state, not
the state at that event).

Read-only: it only reads events.csv and writes cases.html next to it.
"""

from __future__ import annotations

import argparse
import csv
import html
import os
from collections import OrderedDict

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e8; --card:#f7f7f9;
        --gui:#b54708; --gui-bg:#fff4e5; --be:#0b6bcb; --be-bg:#e8f2fd; --bad:#b42318; --bad-bg:#fdecea; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151517; --fg:#ececf0; --muted:#9a9aa3; --line:#2c2c31; --card:#1e1e22;
          --gui:#f5a524; --gui-bg:#3a2a10; --be:#6cb4ff; --be-bg:#13283f; --bad:#ff8a80; --bad-bg:#3d1b19; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
       font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1400px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 16px; }
.legend span { display:inline-block; margin-right:14px; }
.filters { margin:12px 0 20px; display:flex; gap:8px; flex-wrap:wrap; }
.filters button { border:1px solid var(--line); background:var(--card); color:var(--fg);
                  border-radius:6px; padding:4px 10px; cursor:pointer; font:inherit; }
.filters button.on { border-color:var(--fg); }
details { border:1px solid var(--line); border-radius:8px; margin:0 0 10px; background:var(--card); }
summary { cursor:pointer; padding:10px 12px; font-weight:600; }
summary .meta { font-weight:400; color:var(--muted); margin-left:8px; }
.wrap { overflow-x:auto; padding:0 12px 12px; }
table { border-collapse:collapse; width:100%; min-width:1100px; background:var(--bg); }
th, td { text-align:left; vertical-align:top; padding:6px 8px; border-top:1px solid var(--line); }
th { font-weight:600; color:var(--muted); font-size:12px; }
td.n { color:var(--muted); width:2.5em; }
.act { font-weight:600; }
.chip { display:inline-block; padding:1px 6px; margin:1px 2px 1px 0; border-radius:4px;
        border:1px solid var(--line); white-space:nowrap; font-size:12.5px; }
.chip.ex { text-decoration:underline; text-underline-offset:3px; font-weight:600; }
.chip.og { color:var(--gui); background:var(--gui-bg); border-color:var(--gui); }
.chip.ob { color:var(--be); background:var(--be-bg); border-color:var(--be); }
.rej { color:var(--bad); background:var(--bad-bg); border-radius:4px; padding:0 4px; font-size:12px; }
.err { color:var(--bad); font-size:12px; }
.state { color:var(--muted); font-size:12.5px; }
a { color:var(--be); }
"""

JS = """
const btns = document.querySelectorAll('.filters button');
btns.forEach(b => b.addEventListener('click', () => {
  btns.forEach(x => x.classList.toggle('on', x === b));
  const f = b.dataset.f;
  document.querySelectorAll('details').forEach(d => {
    d.style.display = (f === 'all' || d.dataset.scenario === f ||
      (f === 'diff' && d.dataset.diff === '1') || (f === 'rej' && d.dataset.rej === '1')) ? '' : 'none';
  });
}));
document.getElementById('expand').addEventListener('click', e => {
  const open = e.target.dataset.open !== '1';
  document.querySelectorAll('details').forEach(d => d.open = open);
  e.target.dataset.open = open ? '1' : '0';
  e.target.textContent = open ? 'Collapse all' : 'Expand all';
});
"""


def split(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def chips(items: list[str], executed: str, other: set[str], cls_only: str) -> str:
    out = []
    for a in items:
        cls = ["chip"]
        if a == executed:
            cls.append("ex")
        if a not in other:
            cls.append(cls_only)
        out.append(f'<span class="{" ".join(cls)}">{html.escape(a)}</span>')
    return "".join(out) or '<span class="state">(empty)</span>'


def build(run_dir: str) -> str:
    path = os.path.join(run_dir, "events.csv")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    cases: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in rows:
        cases.setdefault(r["case_id"], []).append(r)
    scenarios = sorted({r.get("scenario", "") for r in rows if r.get("scenario")})

    parts = []
    for cid, evs in cases.items():
        sc = evs[0].get("scenario", "")
        n_diff = sum(1 for e in evs if set(split(e["enabled_activities_gui"])) != set(split(e["enabled_activities_backend"])))
        n_rej = sum(1 for e in evs if e.get("outcome") == "rejected")
        trace = " → ".join(e["activity"] for e in evs)
        body = []
        for i, e in enumerate(evs, 1):
            gui, be = split(e["enabled_activities_gui"]), split(e["enabled_activities_backend"])
            act = e["activity"]
            rej = ' <span class="rej">rejected</span>' if e.get("outcome") == "rejected" else ""
            err = f'<div class="err">{html.escape(e.get("error", ""))}</div>' if e.get("error") else ""
            # Odoo names unposted drafts "/": fall back to model and id
            name = (e.get("doc_name") or "").strip()
            doc = html.escape(name if name not in ("", "/") else
                              f'{e.get("doc_model", "")} #{e.get("doc_id", "")}'.strip(" #"))
            url = e.get("browser_url", "")
            link = f' <a href="{html.escape(url)}" target="_blank" rel="noopener">open</a>' if url.startswith("http") else ""
            state = html.escape(e.get("doc_state", "") or "–") + " → " + html.escape(e.get("doc_state_after", "") or "–")
            body.append(
                f'<tr><td class="n">{i}</td>'
                f'<td class="state">{html.escape(e["timestamp"][11:19])}</td>'
                f'<td><span class="act">{html.escape(act)}</span>{rej}{err}</td>'
                f'<td>{html.escape(e.get("role", ""))}<div class="state">{html.escape(e.get("user", ""))}</div></td>'
                f'<td>{doc}{link}<div class="state">{state}</div></td>'
                f'<td>{chips(gui, act, set(be), "og")}</td>'
                f'<td>{chips(be, act, set(gui), "ob")}</td></tr>'
            )
        parts.append(
            f'<details data-scenario="{html.escape(sc)}" data-diff="{int(n_diff > 0)}" data-rej="{int(n_rej > 0)}">'
            f'<summary>{html.escape(cid)}<span class="meta">{html.escape(sc)} · {len(evs)} events'
            f'{f" · {n_diff} with differing sets" if n_diff else ""}{f" · {n_rej} rejected" if n_rej else ""}</span>'
            f'<div class="state" style="font-weight:400;margin-top:4px">{html.escape(trace)}</div></summary>'
            f'<div class="wrap"><table><thead><tr><th>#</th><th>time</th><th>executed activity</th><th>role / user</th>'
            f'<th>document: state before → after</th><th>GUI enabled set</th><th>backend enabled set</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></details>'
        )

    flt = ['<button data-f="all" class="on">All cases</button>']
    flt += [f'<button data-f="{html.escape(s)}">{html.escape(s)}</button>' for s in scenarios]
    flt += ['<button data-f="diff">Sets differ</button>', '<button data-f="rej">Rejected attempts</button>',
            '<button id="expand">Expand all</button>']
    name = os.path.basename(os.path.normpath(run_dir))
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>Case viewer</title><style>{CSS}</style></head><body><main>"
        f"<h1>Case viewer · {html.escape(name)}</h1>"
        f'<p class="sub">{len(cases)} cases, {len(rows)} events. Click a case to see its events.</p>'
        '<p class="legend"><span><span class="chip ex">underlined</span> executed activity</span>'
        '<span><span class="chip og">orange</span> only in GUI set (shown, server would refuse)</span>'
        '<span><span class="chip ob">blue</span> only in backend set (allowed, not shown)</span></p>'
        f'<div class="filters">{"".join(flt)}</div>{"".join(parts)}'
        f"<script>{JS}</script></main></body></html>"
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m sim.viewer", description=__doc__.split("\n\n")[0])
    p.add_argument("run_dir", help="run folder containing events.csv")
    p.add_argument("--out", help="output HTML file (default <run_dir>/cases.html)")
    a = p.parse_args()
    out = a.out or os.path.join(a.run_dir, "cases.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(a.run_dir))
    print(out)


if __name__ == "__main__":
    main()
