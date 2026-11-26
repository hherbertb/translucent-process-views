"""Development helper: show what the snapshot sees on one Odoo screen.

    python -m sim.probe buyer "id=3&model=purchase.order&view_type=form"
    python -m sim.probe reporter /my/tickets
    python -m sim.probe sales "id=1&model=sale.order&view_type=form" --click "button[name=action_cancel]"

Prints the status bar, dialog title and every visible, enabled button
(text | Odoo name | classes) after the optional clicks.
"""
from __future__ import annotations

import argparse

from playwright.sync_api import sync_playwright

from . import config
from .browser import RoleSession

NOISE = ("o-mail", "o_pager", "dropdown-toggle", "o_switch_view", "o_searchview", "fa-trash")


def show(s: RoleSession, label: str) -> None:
    s.idle()
    snap = s.snapshot()
    print(f"== {label}\n   url={snap['url']}\n   title={snap['title']!r} model={snap['model']} "
          f"view={snap['view']} status={snap['status']!r} modal={snap['modal_title']!r} "
          f"editable={snap['editable']} values={snap.get('values')}")
    for b in snap["actions"]:
        if any(n in (b["cls"] or "") for n in NOISE):
            continue
        print(f"   [{b['text']}] name={b['name']} cls={(b['cls'] or '')[:60]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("role")
    ap.add_argument("target", help="URL fragment after /web# , or a path starting with /")
    ap.add_argument("--click", action="append", default=[], help="selector to click, repeatable")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not a.headed)
        s = RoleSession(browser, a.role)
        s.login()
        if a.target.startswith("/"):
            s.page.goto(config.URL + a.target)
        else:
            s.page.goto(f"{config.URL}/web#{a.target}")
        s.page.wait_for_timeout(2500)
        show(s, a.target)
        for sel in a.click:
            s.page.locator(sel).locator("visible=true").first.click()
            s.page.wait_for_timeout(800)
            show(s, f"after click {sel}")
        browser.close()


if __name__ == "__main__":
    main()
