"""Playwright helpers: one logged-in browser context per role."""
from __future__ import annotations

import re
import time

from playwright.sync_api import Browser, Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from . import config

# Snapshot of what is clickable on screen. If a dialog is open only the
# top-most dialog counts: the form behind it is covered by the backdrop.
SNAPSHOT_JS = r"""
(fields) => {
  const vis = e => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const modal = [...document.querySelectorAll('.modal')].filter(vis).pop() || null;
  const portal = !location.pathname.startsWith('/web');
  const root = modal || document.querySelector('.o_action_manager')
    || document.querySelector('#wrapwrap main') || document.body;
  const hash = new URLSearchParams(location.hash.slice(1));
  const form = document.querySelector('.o_action_manager .o_form_view');
  const list = document.querySelector('.o_action_manager .o_list_view');
  const cur = document.querySelector('.o_statusbar_status .o_arrow_button_current');
  const editable = {}, values = {};
  if (form) for (const f of fields) {
    const w = form.querySelector(`.o_field_widget[name="${f}"]`);
    editable[f] = !!(w && vis(w) && !w.classList.contains('o_readonly_modifier'));
    const inp = w && w.querySelector('input, textarea');
    values[f] = w ? (inp ? inp.value : w.innerText).trim().slice(0, 80) : null;
  }
  const actions = [...root.querySelectorAll('button, a.btn, a[role=button], a[role=menuitem]')]
    .filter(b => vis(b) && !b.disabled && !b.classList.contains('disabled'))
    .map(b => ({
      text: (b.innerText || b.getAttribute('title') || b.getAttribute('aria-label') || '')
              .trim().replace(/\s+/g, ' ').slice(0, 60),
      name: b.getAttribute('name'), type: b.getAttribute('type'),
      special: b.getAttribute('special'), cls: b.className,
      stage: !!b.closest('.o_statusbar_status'), value: b.getAttribute('data-value'),
    }));
  return {
    url: location.href, title: document.title, model: hash.get('model'),
    path: location.pathname, portal,
    view: portal ? 'portal' : (form ? 'form' : (list ? 'list' : null)),
    // first span only: duration widgets append e.g. "3h" in a second span
    status: cur ? (cur.querySelector('span') || cur).innerText.trim() : null,
    status_value: cur ? cur.getAttribute('data-value') : null,
    form_readonly: !!(form && form.querySelector('.o_form_readonly')),
    editable, values, modal: !!modal,
    modal_title: modal ? ((modal.querySelector('.modal-title') || {}).innerText || '') : null,
    actions,
  };
}
"""

# Description of the element about to be clicked (recorder-compatible fields).
ELEMENT_JS = r"""
(el) => {
  const xp = e => {
    const parts = [];
    for (; e && e.nodeType === 1; e = e.parentNode) {
      if (e.id) { parts.unshift(`//*[@id="${e.id}"]`); return parts.join('/'); }
      let i = 1; for (let s = e.previousElementSibling; s; s = s.previousElementSibling)
        if (s.tagName === e.tagName) i++;
      parts.unshift(`${e.tagName.toLowerCase()}[${i}]`);
    }
    return '/' + parts.join('/');
  };
  const css = e => {
    const tag = e.tagName.toLowerCase();
    const uniq = s => document.querySelectorAll(s).length === 1;
    if (e.id && uniq('#' + CSS.escape(e.id))) return '#' + CSS.escape(e.id);
    const n = e.getAttribute('name');
    const scope = e.closest('.modal') ? '.modal ' : '';
    if (n && uniq(`${scope}${tag}[name="${n}"]`)) return `${scope}${tag}[name="${n}"]`;
    const cls = [...e.classList].filter(c => c.startsWith('o_'));
    for (const c of cls) if (uniq(`${scope}${tag}.${c}`)) return `${scope}${tag}.${c}`;
    const parts = [];
    for (let x = e; x && x.nodeType === 1 && x !== document.body; x = x.parentNode) {
      let i = 1; for (let s = x.previousElementSibling; s; s = s.previousElementSibling)
        if (s.tagName === x.tagName) i++;
      parts.unshift(`${x.tagName.toLowerCase()}:nth-of-type(${i})`);
    }
    return 'body > ' + parts.join(' > ');
  };
  const r = el.getBoundingClientRect();
  return {
    element_name: (el.innerText || el.getAttribute('title') || el.getAttribute('aria-label') || '')
                    .trim().replace(/\s+/g, ' ').slice(0, 80),
    element_type: el.tagName.toLowerCase(),
    element_id: el.id || el.getAttribute('name') || '',
    element_rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)].join(','),
    x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
    dom_path: css(el), element_xpath: xp(el),
    dom_html: el.outerHTML.replace(/\s+/g, ' ').slice(0, 400),
  };
}
"""

ERROR_DIALOG = ".modal .o_error_dialog, .modal.o_error_dialog, .o_error_dialog"


class RoleSession:
    """A browser page logged in as one role's user."""

    def __init__(self, browser: Browser, role: str, slow_mo_wait: float = 0.0):
        self.role = role
        self.spec = config.ROLES[role]
        self.ctx = browser.new_context(viewport={"width": 1500, "height": 950}, locale="en-US")
        self.page: Page = self.ctx.new_page()
        self.page.set_default_timeout(20000)
        self._inflight = 0
        self.page.on("request", self._req)
        self.page.on("requestfinished", self._done)
        self.page.on("requestfailed", self._done)
        self.settle = slow_mo_wait
        self._nav = 0

    # -- network bookkeeping (to know when Odoo finished its RPC calls) --------
    def _is_rpc(self, req) -> bool:
        return req.resource_type in ("xhr", "fetch") and "/longpolling" not in req.url \
            and "/websocket" not in req.url

    def _req(self, req):
        if self._is_rpc(req):
            self._inflight += 1

    def _done(self, req):
        if self._is_rpc(req):
            self._inflight = max(0, self._inflight - 1)

    def idle(self, quiet_ms: int = 250, timeout: float = 20.0) -> None:
        """Wait until no RPC has been in flight for `quiet_ms`."""
        deadline = time.time() + timeout
        quiet = 0
        while time.time() < deadline:
            self.page.wait_for_timeout(50)
            quiet = quiet + 50 if self._inflight == 0 else 0
            if quiet >= quiet_ms:
                break
        if self.settle:
            self.page.wait_for_timeout(int(self.settle * 1000))

    # -- navigation ----------------------------------------------------------
    def login(self) -> None:
        p = self.page
        p.goto(f"{config.URL}/web/login")
        p.fill("input[name=login]", self.spec["login"])
        p.fill("input[name=password]", self.spec["password"])
        p.click("button[type=submit]")
        # internal users land in the web client, portal users on /my
        p.wait_for_url(lambda u: "/web/login" not in u)
        p.wait_for_load_state("domcontentloaded")
        self.idle()

    def _goto(self, fragment: str, ready: str) -> None:
        # a changed query string forces a full load, so every visit starts from
        # fresh server data (other roles change the same documents)
        self._nav += 1
        self.page.goto(f"{config.URL}/web?v={self._nav}#{fragment}")
        self.page.wait_for_selector(ready)
        self.idle()

    def open_form(self, model: str, rec_id: int) -> None:
        self._goto(f"id={rec_id}&model={model}&view_type=form", ".o_form_view .o_form_sheet_bg, .o_form_view .o_form_sheet")

    def open_list(self, action_xmlid: str) -> None:
        self._goto(f"action={action_xmlid}", ".o_list_view")

    # -- observation ---------------------------------------------------------
    # form fields whose editability / value the snapshot reports
    watch_fields: tuple = ("order_line", "move_ids_without_package", "invoice_date",
                           "user_id", "team_id")

    def snapshot(self) -> dict:
        return self.page.evaluate(SNAPSHOT_JS, list(self.watch_fields))

    def open_path(self, path: str, ready: str) -> None:
        """Portal pages (server-rendered, outside the web client)."""
        self.page.goto(f"{config.URL}{path}")
        self.page.wait_for_selector(ready)
        self.idle()

    def describe(self, loc: Locator) -> dict:
        return loc.evaluate(ELEMENT_JS)

    def record_id(self) -> int | None:
        m = re.search(r"[#&]id=(\d+)", self.page.url)
        return int(m.group(1)) if m else None

    def error_text(self) -> str | None:
        loc = self.page.locator(ERROR_DIALOG)
        if loc.count() and loc.first.is_visible():
            body = loc.first.locator(".modal-body")
            txt = (body.first.inner_text() if body.count() else loc.first.inner_text())
            return re.sub(r"\s+", " ", txt).strip()[:300]
        return None

    def close_error(self) -> None:
        self.page.locator(f"{ERROR_DIALOG}").first.locator("button.btn-primary, .btn-close").first.click()
        self.page.wait_for_selector(ERROR_DIALOG, state="hidden")
        self.clear_hover()
        self.idle()

    def clear_hover(self) -> None:
        """Move the pointer to an empty spot: Odoo closes hover tooltips on
        mouse-leave, and an open tooltip intercepts clicks on what it covers."""
        self.page.mouse.move(2, 2)
        try:
            self.page.locator(".o-tooltip").first.wait_for(state="detached", timeout=2000)
        except PlaywrightTimeout:
            pass  # tooltip still fading; the following click retries until it is gone

    def wait_for(self, pred, timeout: float = 25.0, what: str = "condition"):
        """Poll `pred()` (truthy result returned) while pumping browser events."""
        deadline = time.time() + timeout
        while True:
            res = pred()
            if res:
                return res
            if time.time() > deadline:
                raise TimeoutError(f"{self.role}: timed out waiting for {what}")
            self.page.wait_for_timeout(100)

    def modal_open(self) -> bool:
        return self.page.locator(".modal:visible").count() > 0

    # -- form input helpers --------------------------------------------------
    def many2one(self, container: str, text: str) -> None:
        inp = self.page.locator(f"{container} input").first
        inp.click()
        inp.fill("")
        inp.press_sequentially(text, delay=10)
        item = self.page.locator(".o-autocomplete--dropdown-menu .o-autocomplete--dropdown-item a",
                                 has_text=text).first
        item.wait_for()
        item.click()
        self.idle(150)

    def set_cell(self, field_widget: str, row: int, column: str, value: str) -> None:
        """Edit one cell of an editable one2many list inside a form."""
        cell = self.page.locator(
            f".o_field_widget[name={field_widget}] tr.o_data_row").nth(row).locator(f"td[name={column}]")
        self.clear_hover()
        cell.click()
        inp = self.page.locator(
            f".o_field_widget[name={field_widget}] tr.o_selected_row td[name={column}] input").first
        inp.wait_for()
        inp.fill(value)
        inp.press("Tab")
        self.idle(150)

    def close(self) -> None:
        self.ctx.close()
