"""Shared machinery of all scenarios.

* `Scenario`  - per-scenario tables: activity vocabulary, how screen buttons
                map to activities (GUI enabled set), the server rule table
                (backend enabled set), which documents belong to a case, and
                the named causes of GUI/backend disagreement.
* `Backend`   - access rights and document facts over XML-RPC.
* `BaseCase`  - one case: private random stream, `event()` (observe both
                enabled sets, click, wait, log), and flows that several
                scenarios share (mail dialog, stock transfer, payment).

Labels never contain a comma: sets are serialised as ``", ".join(sorted(s))``.
"""
from __future__ import annotations

import datetime as dt
import random
import time

from .browser import RoleSession
from .rpc import Odoo

SAVE = ".o_form_button_save"
PICKING, MOVE = "stock.picking", "account.move"


# --- scenario description ---------------------------------------------------
class Scenario:
    name = ""            # value of the `scenario` column
    prefix = ""          # case id prefix, unique per scenario
    roles: tuple = ()    # roles that need a browser session
    ROOT = ""            # model of the document that carries the case
    CREATE = ""          # activity of the "New" button on ROOT screens
    START = ""           # first activity of a case, if not CREATE
    SHORT: dict = {}     # model -> short name used in `case_state`
    FORM_BUTTONS: dict = {}    # (model, button name | "text:<caption>") -> activity | f(snap)
    EDIT_FIELDS: dict = {}     # (model, field) -> activity | f(snap)
    WIZARDS: dict = {}         # primary button name -> wizard kind
    WIZARD_BUTTONS: dict = {}  # (kind, button name) -> activity | f(snap)
    WIZARD_DISCARD: dict = {}  # kind -> activity of the Discard/Cancel button
    VOCABULARY: tuple = ()
    NEVER_EXECUTED: tuple = ()  # in the vocabulary, deliberately not performed by agents
    # (cause id, side, activity, explanation); side is "only_gui" or "only_backend"
    CAUSES: tuple = ()
    # model -> [(state-label part index, field, kind)], kind: selection | many2one | untracked
    TRACKED: dict = {}
    # transitions Odoo performs without writing a tracking value:
    # (model, field, old, new) -> reason. Check f accepts them only where the
    # tracked transitions before and after line up.
    UNTRACKED: dict = {}

    # -- GUI derivation ------------------------------------------------------
    def wizard_kind(self, snap: dict) -> str | None:
        if not snap.get("modal"):
            return None
        for b in snap["actions"]:
            if b.get("name") in self.WIZARDS:
                return self.WIZARDS[b["name"]]
        return "unknown"

    @staticmethod
    def _resolve(value, snap):
        return value(snap) if callable(value) else value

    def map_button(self, snap: dict, b: dict, kind: str | None) -> str | None:
        model = snap.get("model")
        name, text, cls = b.get("name") or "", b.get("text") or "", b.get("cls") or ""
        if kind:
            act = self._resolve(self.WIZARD_BUTTONS.get((kind, name)), snap)
            if not act and b.get("special") == "cancel":
                act = self._resolve(self.WIZARD_DISCARD.get(kind), snap)
            return act
        if b.get("stage"):
            return self.map_stage(snap, text)
        for key in ((model, name), (model, "text:" + text)):
            if key in self.FORM_BUTTONS and key[1]:
                return self._resolve(self.FORM_BUTTONS[key], snap)
        if model == self.ROOT and self.CREATE and not snap.get("portal") and (
                "o_list_button_add" in cls or "o_form_button_create" in cls):
            return self.CREATE
        return None

    def map_stage(self, snap: dict, text: str) -> str | None:  # clickable status-bar stages
        return None

    def gui(self, snap: dict) -> tuple[set[str], list[str]]:
        """Map a screen snapshot to (activities, other visible button captions)."""
        acts: set[str] = set()
        other: list[str] = []
        kind = self.wizard_kind(snap)
        for b in snap["actions"]:
            act = self.map_button(snap, b, kind)
            if act:
                acts.add(act)
            elif b.get("text") and b["text"] not in other:
                other.append(b["text"])
        if not kind and not snap.get("form_readonly"):
            for (m, field), act in self.EDIT_FIELDS.items():
                if m == snap.get("model") and snap.get("editable", {}).get(field):
                    act = self._resolve(act, snap)
                    if act:
                        acts.add(act)
        return acts, other

    # -- backend derivation (implemented per scenario) -----------------------
    def facts(self, be: "Backend", model: str, rec_id: int) -> dict:
        raise NotImplementedError

    def rules(self, be: "Backend", role: str, model: str | None, f: dict | None,
              wizard: str | None = None) -> set[str]:
        raise NotImplementedError

    def state_label(self, model: str, f: dict) -> str:
        return f["state"]

    def case_docs(self, be: "Backend", root_id: int) -> list[tuple[str, int]]:
        return [(self.ROOT, root_id)]

    def case_roles(self) -> tuple:
        return self.roles

    def explain(self, side: str, activity: str, row: dict) -> str | None:
        """Named cause of one GUI/backend difference, or None if unexplained."""
        for cause, c_side, c_act, _text in self.CAUSES:
            if c_side == side and c_act == activity:
                return cause
        return None


# --- backend ----------------------------------------------------------------
class Backend:
    """Access rights are asked *as the acting user* (`check_access_rights`,
    `has_group`, record-rule filtered `search_count`); document facts are read
    with the admin user so that they do not depend on who asks."""

    def __init__(self, admin: Odoo, users: dict[str, Odoo]):
        self.admin = admin
        self.users = users
        self._cache: dict = {}
        # every exception caught here, so that none is swallowed silently:
        # (kind, role, call, message). kind "denied" = the server's answer to
        # an access question; anything else is unexpected.
        self.caught: list[tuple] = []
        self.company = admin.search_read(
            "res.company", [], ["po_double_validation", "po_double_validation_amount"])[0]

    def _note(self, role: str, call: str, exc: Exception) -> None:
        msg = str(exc)
        denied = ("AccessError" in msg or "Access Denied" in msg or "not allowed to" in msg
                  or "AccessDenied" in msg)
        self.caught.append(("denied" if denied else "unexpected", role, call, " ".join(msg.split())[-300:]))

    def right(self, role: str, model: str, op: str) -> bool:
        key = (role, model, op)
        if key not in self._cache:
            try:
                self._cache[key] = bool(self.users[role].call(
                    model, "check_access_rights", op, raise_exception=False))
            except Exception as exc:  # noqa: BLE001 - e.g. portal users may not call this at all
                self._note(role, f"{model}.check_access_rights({op})", exc)
                self._cache[key] = False
        return self._cache[key]

    def group(self, role: str, xmlid: str) -> bool:
        key = (role, "group", xmlid)
        if key not in self._cache:
            try:
                self._cache[key] = bool(self.users[role].call("res.users", "has_group", xmlid))
            except Exception as exc:  # noqa: BLE001
                self._note(role, f"has_group({xmlid})", exc)
                self._cache[key] = False
        return self._cache[key]

    def can_see(self, role: str, model: str, rec_id: int) -> bool:
        if not self.right(role, model, "read"):
            return False
        try:
            return self.users[role].call(model, "search_count", [("id", "=", rec_id)]) > 0
        except Exception as exc:  # noqa: BLE001
            self._note(role, f"{model}.search_count", exc)
            return False

    def can_write(self, role: str, model: str, rec_id: int) -> bool:
        """Write access including record rules."""
        if not self.right(role, model, "write"):
            return False
        try:
            self.users[role].call_void(model, "check_access_rule", [rec_id], "write")
            return True
        except Exception as exc:  # noqa: BLE001 - AccessError is the expected "no"
            self._note(role, f"{model}.check_access_rule(write)", exc)
            return False

    def enabled(self, sc: Scenario, role: str, model: str | None, rec_id: int | None,
                wizard: str | None = None) -> tuple[set[str], dict | None]:
        """Enabled set for the acting user on the document on screen."""
        if rec_id is None:
            return sc.rules(self, role, model, None, wizard), None
        f = sc.facts(self, model, rec_id)
        f["_id"] = rec_id
        if not self.can_see(role, model, rec_id):
            return set(), f
        return sc.rules(self, role, model, f, wizard), f

    def case_view(self, sc: Scenario, root_id: int | None) -> tuple[set[str], str]:
        """Enabled set over all documents of the case and all roles of the
        scenario, plus a compact description of the case state."""
        if root_id is None:
            return {sc.START or sc.CREATE}, ""
        out: set[str] = set()
        docs = sc.case_docs(self, root_id)
        # which documents each role may see: one search per role and model
        by_model: dict[str, list[int]] = {}
        for model, rec_id in docs:
            by_model.setdefault(model, []).append(rec_id)
        visible: dict[tuple, set] = {}
        for role in sc.case_roles():
            for model, ids in by_model.items():
                if not self.right(role, model, "read"):
                    visible[(role, model)] = set()
                    continue
                try:
                    visible[(role, model)] = set(self.users[role].search(model, [("id", "in", ids)]))
                except Exception as exc:  # noqa: BLE001
                    self._note(role, f"{model}.search", exc)
                    visible[(role, model)] = set()
        parts = []
        for model, rec_id in docs:
            f = sc.facts(self, model, rec_id)
            f["_id"] = rec_id
            for role in sc.case_roles():
                if rec_id in visible[(role, model)]:
                    out |= sc.rules(self, role, model, f)
            parts.append(f"{sc.SHORT[model]}:{rec_id}={sc.state_label(model, f)}")
        out.discard(sc.CREATE)  # starts another case, not a step of this one
        return out, ";".join(parts)

    def case_states(self, sc: Scenario, root_id: int | None) -> str:
        """Only the state description of `case_view` (no access questions)."""
        if root_id is None:
            return ""
        return ";".join(f"{sc.SHORT[m]}:{i}={sc.state_label(m, sc.facts(self, m, i))}"
                        for m, i in sc.case_docs(self, root_id))


# --- case -------------------------------------------------------------------
class BaseCase:
    sc: Scenario

    def __init__(self, sim, index: int):
        self.sim = sim
        self.index = index
        self.case_id = f"{self.sc.prefix}{index + 1:04d}"
        self.rng = random.Random(f"{sim.seed}/{self.sc.name}/case/{index}")
        self.root_id: int | None = None
        self.plan = self.draw_plan()

    def draw_plan(self) -> dict:
        raise NotImplementedError

    def run(self):
        raise NotImplementedError

    # -- plumbing ------------------------------------------------------------
    @property
    def admin(self) -> Odoo:
        return self.sim.admin

    def think(self) -> None:
        # the draw always happens so that the random stream does not depend
        # on the chosen think-time scale
        pause = min(self.rng.expovariate(1 / 0.4), 3.0) * self.sim.think_scale
        if pause > 0:
            time.sleep(pause)

    def s(self, role: str) -> RoleSession:
        return self.sim.sessions[role]

    def facts(self, model: str, rec_id: int) -> dict:
        return self.sc.facts(self.sim.backend, model, rec_id)

    def root(self) -> dict:
        return self.facts(self.sc.ROOT, self.root_id)

    def event(self, s: RoleSession, activity: str, target: str, model: str, rec_id: int | None,
              wizard: str | None = None, pre=None, post=None) -> bool:
        """Observe both enabled sets, click `target`, wait, log one event.

        `pre`  fills in fields before the click (edit activities).
        `post` waits for the effect and returns an error text if Odoo refused.
        Returns True if the action went through.
        """
        self.think()
        be, sc = self.sim.backend, self.sc
        snap = s.snapshot()
        gui, other = sc.gui(snap)
        backend, facts = be.enabled(sc, s.role, model, rec_id, wizard)
        case_set, case_state = be.case_view(sc, self.root_id)
        case_set |= (backend - {sc.CREATE}) if self.root_id else backend  # incl. an open dialog
        if pre:
            pre()
        loc = s.page.locator(target).locator("visible=true").first
        loc.wait_for(state="visible")
        el = s.describe(loc)
        stamp = dt.datetime.now().astimezone().isoformat(timespec="milliseconds")
        url, title = s.page.url, s.page.title()
        loc.click()
        error = post() if post else None
        s.idle()

        doc_id = rec_id if rec_id is not None else (self.root_id if model == sc.ROOT else None)
        after = sc.facts(be, model, doc_id) if doc_id else None
        case_state_after = be.case_states(sc, self.root_id)
        self.sim.log({
            "timestamp": stamp, "case_id": self.case_id, "scenario": sc.name, "activity": activity,
            "event_type": "click", "outcome": "rejected" if error else "ok", "error": error or "",
            "role": s.role, "user": s.spec["login"],
            "doc_model": model, "doc_id": doc_id or "",
            "doc_name": (after or {}).get("name") or "",
            "doc_state": sc.state_label(model, facts) if facts else "",
            "doc_state_after": sc.state_label(model, after) if after else "",
            "case_state": case_state, "case_state_after": case_state_after,
            "gui": gui, "backend": backend, "backend_case": case_set,
            "gui_other_actions": " | ".join(other),
            "active_app": "Odoo", "active_window_title": title, "browser_url": url,
            "element_source": "dom", **el,
        })
        return not error

    def settle(self, s: RoleSession, done) -> str | None:
        """Wait until `done()` holds or Odoo shows an error dialog."""
        res = s.wait_for(lambda: s.error_text() or (done() and "ok"), what="action result")
        if res == "ok":
            # Odoo renders an error dialog's body a moment after the dialog
            # itself; look once more before calling the action a success
            s.page.wait_for_timeout(300)
            res = s.error_text() or "ok"
        if res != "ok":
            s.close_error()
            return res
        return None

    def save_done(self, s: RoleSession) -> str | None:
        s.idle()
        return self.settle(s, lambda: s.page.locator(SAVE).locator("visible=true").count() == 0)

    def button(self, s: RoleSession, activity: str, model: str, rec_id: int, name: str, done,
               wizard: str | None = None, confirm: bool = False) -> bool:
        """Click a form (or dialog) button given by its Odoo name or `text:<caption>`.

        `confirm`: the button has Odoo's `confirm=` attribute ("Are you sure
        ...?"); the agent answers Ok as part of the same event."""
        scope = ".modal" if wizard else ".o_form_view"
        if name.startswith("text:"):
            # Odoo wraps captions in a <span>; :text-is matches the innermost element
            cap = name[5:]
            sel = f"{scope} button:has(span:text-is('{cap}')), {scope} button:text-is('{cap}')"
        else:
            sel = f"{scope} button[name={name}]"
        if confirm:
            def post():
                ok = s.page.locator(".modal footer button.btn-primary").locator("visible=true").first
                ok.wait_for(state="visible")
                ok.click()
                s.idle()
                return self.settle(s, done)
            return self.event(s, activity, sel, model, rec_id, wizard=wizard, post=post)
        return self.event(s, activity, sel, model, rec_id, wizard=wizard,
                          post=lambda: self.settle(s, done))

    def discard(self, s: RoleSession, activity: str, model: str, rec_id: int, wizard: str) -> bool:
        sel = ".modal footer button[special=cancel]"
        return self.event(s, activity, sel, model, rec_id, wizard=wizard,
                          post=lambda: self.settle(s, lambda: not s.modal_open()))

    def interleave(self, *gens):
        """Advance the given tracks one session at a time in random order."""
        live = list(gens)
        while live:
            g = self.rng.choice(live)
            try:
                next(g)
            except StopIteration:
                live.remove(g)
                continue
            yield

    # -- flows shared by scenarios -------------------------------------------
    def mail_dialog(self, s: RoleSession, model: str, rec_id: int, open_name: str,
                    compose: str, send: str, discard_label: str, discard: bool, sent) -> None:
        """Open Odoo's mail composer from a form button, then send or discard."""
        self.button(s, compose, model, rec_id, open_name,
                    lambda: s.page.locator(".modal button[name=action_send_mail]").is_visible())
        s.idle(400)
        if discard:
            self.discard(s, discard_label, model, rec_id, "mail")
        else:
            self.button(s, send, model, rec_id, "action_send_mail",
                        lambda: not s.modal_open() and sent(), wizard="mail")

    def set_cell_event(self, s: RoleSession, activity: str, model: str, rec_id: int,
                       widget: str, column: str, value) -> bool:
        return self.event(s, activity, SAVE, model, rec_id,
                          pre=lambda: s.set_cell(widget, 0, column, str(value)),
                          post=lambda: self.save_done(s))

    def transfer(self, role: str, pid: int, mode: str, L: dict, wrong_qty: bool = False,
                 zero_qty: bool = False, backorder_discard: bool = False):
        """One stock transfer (receipt or delivery): optional quantity
        corrections, validate, answer the backorder question.

        mode: full | backorder | no_backorder. `L` holds the activity labels:
        set_qty, validate, create_backorder, no_backorder, discard_backorder.
        """
        s = self.s(role)
        s.open_form(PICKING, pid)
        move_id = self.admin.read(PICKING, [pid], ["move_ids"])[0]["move_ids"][0]
        demand = int(self.admin.read("stock.move", [move_id], ["product_uom_qty"])[0]["product_uom_qty"])
        if mode != "full" and demand < 2:
            mode = "full"
        state = lambda: self.admin.read(PICKING, [pid], ["state"])[0]["state"]  # noqa: E731
        done = lambda: state() == "done"  # noqa: E731
        backorder_asked = lambda: s.page.locator(".modal button[name=process]").is_visible()  # noqa: E731
        set_qty = lambda q: self.set_cell_event(  # noqa: E731
            s, L["set_qty"], PICKING, pid, "move_ids_without_package", "quantity", q)
        validate = lambda: self.event(  # noqa: E731
            s, L["validate"], ".o_form_view button[name=button_validate]", PICKING, pid,
            post=lambda: self.settle(s, lambda: backorder_asked() or done()))
        if zero_qty:
            # quantity wiped by mistake: Odoo refuses to validate an empty transfer
            n_moves = len(self.admin.read(PICKING, [pid], ["move_ids"])[0]["move_ids"])
            if n_moves == 1:
                set_qty(0)
                validate()
                if mode == "full":
                    set_qty(demand)
        if wrong_qty:
            # typo: an extra digit, noticed and corrected right away
            set_qty(demand * 10 + self.rng.randint(0, 9))
            if mode == "full":
                set_qty(demand)
        if mode != "full":
            set_qty(max(1, min(demand - 1, int(demand * self.plan["partial_fraction"]))))
        validate()
        if backorder_asked():
            s.idle(300)
            if backorder_discard:
                self.discard(s, L["discard_backorder"], PICKING, pid, "backorder")
                validate()
                s.idle(300)
            if mode == "backorder":
                self.button(s, L["create_backorder"], PICKING, pid, "process", done, wizard="backorder")
            else:
                self.button(s, L["no_backorder"], PICKING, pid, "process_cancel_backorder", done,
                            wizard="backorder")
        yield

    def pay(self, role: str, move_id: int, L: dict, discard_first: bool = False):
        """Register a payment on a posted bill / invoice.
        `L`: register, create, discard."""
        s = self.s(role)
        s.open_form(MOVE, move_id)
        up = lambda: s.page.locator(".modal button[name=action_create_payments]").is_visible()  # noqa: E731
        register = lambda: self.button(  # noqa: E731
            s, L["register"], MOVE, move_id, "action_register_payment", up)
        register()
        s.idle(300)
        if discard_first:
            self.discard(s, L["discard"], MOVE, move_id, "payment")
            register()
            s.idle(300)
        paid = lambda: self.admin.read(MOVE, [move_id], ["payment_state"])[0][  # noqa: E731
            "payment_state"] in ("paid", "in_payment")
        self.button(s, L["create"], MOVE, move_id, "action_create_payments",
                    lambda: not s.modal_open() and paid(), wizard="payment")
        yield


def picking_facts(be: Backend, rec_id: int) -> dict:
    f = be.admin.read(PICKING, [rec_id], ["name", "state", "move_ids", "picking_type_code"])[0]
    moves = be.admin.read("stock.move", f["move_ids"], ["product_uom_qty", "quantity"])
    f["any_qty"] = any(m["quantity"] > 0 for m in moves)
    f["short"] = any(m["quantity"] < m["product_uom_qty"] for m in moves)
    return f


def move_facts(be: Backend, rec_id: int) -> dict:
    return be.admin.read(MOVE, [rec_id], ["name", "state", "payment_state", "invoice_date",
                                          "invoice_line_ids", "move_type", "reversal_move_id"])[0]
