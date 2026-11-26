"""Scenario 3: ticket handling (OCA helpdesk_mgmt 17.0, AGPL-3).

One case = one support ticket, from the customer's portal submission to
Done / Cancelled / Rejected. The customer works in the Odoo portal
(server-rendered pages under /my), the support staff in the web client.
"""
from __future__ import annotations

import re

from . import config
from .core import SAVE, Backend, BaseCase, Scenario

TICKET = "helpdesk.ticket"

SUBMIT_TICKET = "Submit Ticket"
REPLY_TO_TICKET = "Reply to Ticket"
CONFIRM_RESOLUTION = "Confirm Resolution"
WITHDRAW_TICKET = "Withdraw Ticket"
CREATE_TICKET = "Create Ticket"
ASSIGN_TO_ME = "Assign to Me"
ASSIGN_TICKET = "Assign Ticket"
REASSIGN_TICKET = "Reassign Ticket"
START_WORK = "Start Work"
RESUME_WORK = "Resume Work"
ACCEPT_ESCALATION = "Accept Escalation"
REOPEN_TICKET = "Reopen Ticket"
RESET_TO_NEW = "Reset to New"
WAIT_FOR_CUSTOMER = "Wait for Customer"
ESCALATE_TICKET = "Escalate Ticket"
RESOLVE_TICKET = "Resolve Ticket"
CLOSE_TICKET = "Close Ticket"
CANCEL_TICKET = "Cancel Ticket"
REJECT_TICKET = "Reject Ticket"

STAGES = [s["name"] for s in config.TICKET_STAGES]
TO_STAGE = {"New": RESET_TO_NEW, "Awaiting": WAIT_FOR_CUSTOMER, "Escalated": ESCALATE_TICKET,
            "Resolved": RESOLVE_TICKET, "Done": CLOSE_TICKET, "Cancelled": CANCEL_TICKET,
            "Rejected": REJECT_TICKET}
PORTAL_STAGES = {s["name"] for s in config.TICKET_STAGES if s.get("portal")}  # Done, Cancelled
PORTAL_CLOSE = {"Done": CONFIRM_RESOLUTION, "Cancelled": WITHDRAW_TICKET}

PROBLEMS = {
    "Hardware": ["Laptop does not boot", "Docking station flickers", "Printer jams on every page"],
    "Software": ["ERP report shows wrong totals", "Mail client crashes on start", "VPN client update fails"],
    "Access": ["Locked out of the HR portal", "Need access to the sales share", "2FA device lost"],
    "Billing": ["Invoice charged twice", "Credit note missing", "Wrong VAT on last invoice"],
}


def move_label(src: str, dst: str) -> str:
    """Activity of moving a ticket from stage `src` to stage `dst`."""
    if dst == "In Progress":
        return {"New": START_WORK, "Awaiting": RESUME_WORK, "Escalated": ACCEPT_ESCALATION}.get(
            src, REOPEN_TICKET)
    return TO_STAGE[dst]


class TicketHandling(Scenario):
    name = "tickets"
    prefix = "TK"
    roles = ("reporter", "agent", "specialist", "lead")
    ROOT = TICKET
    CREATE = CREATE_TICKET
    START = SUBMIT_TICKET
    SHORT = {TICKET: "ticket"}
    FORM_BUTTONS = {(TICKET, "assign_to_me"): ASSIGN_TO_ME}
    EDIT_FIELDS = {(TICKET, "user_id"): lambda s: REASSIGN_TICKET if (s.get("values") or {}).get("user_id")
                   else ASSIGN_TICKET}
    VOCABULARY = (SUBMIT_TICKET, REPLY_TO_TICKET, CONFIRM_RESOLUTION, WITHDRAW_TICKET, CREATE_TICKET,
                  ASSIGN_TO_ME, ASSIGN_TICKET, REASSIGN_TICKET, START_WORK, RESUME_WORK,
                  ACCEPT_ESCALATION, REOPEN_TICKET, RESET_TO_NEW, WAIT_FOR_CUSTOMER, ESCALATE_TICKET,
                  RESOLVE_TICKET, CLOSE_TICKET, CANCEL_TICKET, REJECT_TICKET)
    NEVER_EXECUTED = (CREATE_TICKET, RESET_TO_NEW)
    CAUSES = (
        ("portal-close-hidden-once-closed", "only_backend", CONFIRM_RESOLUTION,
         "The portal page hides its close buttons once the ticket has a closed date; the "
         "/ticket/close controller still accepts them (it only checks the target stage)."),
        ("portal-close-hidden-once-closed", "only_backend", WITHDRAW_TICKET,
         "As above, for the Cancelled button."),
    )
    TRACKED = {TICKET: [(0, "stage_id", "many2one"), (1, "user_id", "many2one")]}

    def __init__(self):
        self.stage_ids: dict[int, str] = {}

    def load_stages(self, admin) -> None:
        if not self.stage_ids:
            rows = admin.search_read("helpdesk.ticket.stage", [], ["name"])
            self.stage_ids = {r["id"]: r["name"] for r in rows}

    def stage_id(self, name: str) -> int:
        return next(i for i, n in self.stage_ids.items() if n == name)

    # -- GUI -----------------------------------------------------------------
    def map_button(self, snap: dict, b: dict, kind: str | None) -> str | None:
        text, cls = b.get("text") or "", b.get("cls") or ""
        if snap.get("portal"):
            path = snap.get("path") or ""
            if path.startswith("/new/ticket") and text == "Submit Ticket":
                return SUBMIT_TICKET
            if re.match(r"^/my/ticket/\d+", path):
                if "o_portal_chatter_composer_btn" in cls:
                    return REPLY_TO_TICKET
                return PORTAL_CLOSE.get(text)
            return None
        if b.get("stage") and b.get("value"):
            cur = self.stage_ids.get(int(snap["status_value"])) if snap.get("status_value") else None
            dst = self.stage_ids.get(int(b["value"]))
            return move_label(cur, dst) if cur and dst else None
        return super().map_button(snap, b, kind)

    # -- backend -------------------------------------------------------------
    def facts(self, be: Backend, model: str, rec_id: int) -> dict:
        self.load_stages(be.admin)
        f = be.admin.read(TICKET, [rec_id], ["number", "name", "stage_id", "user_id", "team_id",
                                             "closed_date", "partner_id"])[0]
        f["title"] = f["name"]
        f["name"] = f["number"]
        f["state"] = f["stage_id"][1] if f["stage_id"] else ""
        return f

    def state_label(self, model: str, f: dict) -> str:
        return f"{f['state']}/{f['user_id'][1] if f['user_id'] else 'unassigned'}"

    def rules(self, be: Backend, role: str, model: str | None, f: dict | None,
              wizard: str | None = None) -> set[str]:
        """Transcribed from helpdesk_mgmt 17.0: models/helpdesk_ticket.py
        (stage and assignee are plain writable fields, `assign_to_me` has no
        guard), controllers/main.py (/submitted/ticket, /ticket/close) and
        portal chatter. Record rules are evaluated by the server
        (`check_access_rule`)."""
        out: set[str] = set()
        if config.ROLES[role].get("portal"):
            if f is None:
                return {SUBMIT_TICKET}  # /submitted/ticket: any logged-in user
            if not be.can_see(role, TICKET, f["_id"]):
                return out
            out.add(REPLY_TO_TICKET)  # portal chatter: read access is enough
            # /ticket/close: any stage flagged close_from_portal, in any state
            out |= {PORTAL_CLOSE[s] for s in PORTAL_STAGES}
            return out
        if model in (None, TICKET) and be.right(role, TICKET, "create") and not wizard:
            out.add(CREATE_TICKET)
        if f is None or not be.can_write(role, TICKET, f["_id"]):
            return out
        cur = f["state"]
        out |= {move_label(cur, dst) for dst in STAGES if dst != cur}
        if f["user_id"]:
            out.add(REASSIGN_TICKET)
        else:
            # the server would run assign_to_me at any time; like other
            # guard-less methods it is limited to its intended source state
            out |= {ASSIGN_TO_ME, ASSIGN_TICKET}
        return out


SCENARIO = TicketHandling()


class Case(BaseCase):
    sc = SCENARIO

    def __init__(self, sim, index: int):
        super().__init__(sim, index)
        self.sc.load_stages(sim.admin)
        self.assignee = None  # role currently working on the ticket

    def draw_plan(self) -> dict:
        r = self.rng
        cat = r.choice(config.TICKET_CATEGORIES)
        return {
            "category": cat,
            "subject": r.choice(PROBLEMS[cat]),
            "withdraw_early": r.random() < 0.05,
            "duplicate": r.random() < 0.08,
            "triage_by_lead": r.random() < 0.4,
            "handover_to_lead": r.random() < 0.08,
            "awaiting": r.random() < 0.35,
            "customer_silent": r.random() < 0.15,
            "second_wait": r.random() < 0.25,
            "escalate": r.random() < 0.30,
            "specialist_waits": r.random() < 0.2,
            "wrong_close": r.random() < 0.06,
            "after_resolve": r.choices(["confirm", "reopen", "silent"], [0.55, 0.2, 0.25])[0],
            "withdraw_late": r.random() < 0.04,
        }

    def t(self) -> dict:
        return self.root()

    def stage_is(self, name: str):
        return lambda: self.t()["state"] == name

    # -- portal (customer) ---------------------------------------------------
    def messages(self) -> int:
        return self.admin.call("mail.message", "search_count",
                               [("model", "=", TICKET), ("res_id", "=", self.root_id),
                                ("message_type", "=", "comment")])

    def submit(self):
        s = self.s("reporter")
        s.open_path("/new/ticket", "form[action*='/submitted/ticket'] button[type=submit]")
        pl = self.plan

        def fill():
            p = s.page
            p.locator("select[name=category]").select_option(label=pl["category"])
            p.locator("input[name=subject]").fill(f"{self.case_id} {pl['subject']}")
            p.locator("textarea[name=description]").fill(
                f"{pl['subject']}. Noticed this morning, please help. ({self.case_id})")

        def done():
            m = s.wait_for(lambda: re.search(r"/my/ticket/(\d+)", s.page.url), what="ticket page")
            self.root_id = int(m.group(1))
            s.page.wait_for_load_state("domcontentloaded")
            return None

        self.event(s, SUBMIT_TICKET, "form[action*='/submitted/ticket'] button[type=submit]", TICKET, None,
                   pre=fill, post=done)
        yield

    def open_portal_ticket(self, s) -> None:
        """Open the ticket the way the customer's notification mail links it:
        with the record's access token. Without the token Odoo refuses portal
        chatter posts ("Access Denied": posting needs write access)."""
        token = self.admin.read(TICKET, [self.root_id], ["access_token"])[0]["access_token"]
        if not token:
            import uuid
            token = str(uuid.UUID(int=self.rng.getrandbits(128)))
            self.admin.write(TICKET, [self.root_id], {"access_token": token})
        s.open_path(f"/my/ticket/{self.root_id}?access_token={token}", "textarea[name=message]")

    def reply(self, text: str):
        s = self.s("reporter")
        self.open_portal_ticket(s)
        before = self.messages()
        self.event(s, REPLY_TO_TICKET, "button.o_portal_chatter_composer_btn", TICKET, self.root_id,
                   pre=lambda: s.page.locator("textarea[name=message]").fill(text),
                   post=lambda: self.settle(s, lambda: self.messages() > before))
        yield

    def portal_close(self, stage: str):
        """Returns False if the portal no longer offers the button."""
        s = self.s("reporter")
        self.open_portal_ticket(s)
        sid = self.sc.stage_id(stage)
        sel = f"form[action='/ticket/close']:has(input[name=stage_id][value='{sid}']) button"
        if s.page.locator(sel).count() == 0:
            return False
        self.event(s, PORTAL_CLOSE[stage], sel, TICKET, self.root_id,
                   post=lambda: self.settle(s, self.stage_is(stage)))
        yield
        return True

    # -- back office ---------------------------------------------------------
    def move(self, role: str, dst: str) -> bool:
        s = self.s(role)
        s.open_form(TICKET, self.root_id)
        label = move_label(self.t()["state"], dst)
        sel = f".o_statusbar_status button[data-value='{self.sc.stage_id(dst)}']"
        return self.event(s, label, sel, TICKET, self.root_id,
                          post=lambda: self.settle(s, self.stage_is(dst)))

    def step(self, role: str, dst: str):
        self.move(role, dst)
        yield

    def assign_to_me(self, role: str):
        s = self.s(role)
        s.open_form(TICKET, self.root_id)
        uid = self.sim.backend.users[role].uid
        self.button(s, ASSIGN_TO_ME, TICKET, self.root_id, "assign_to_me",
                    lambda: (self.t()["user_id"] or [0])[0] == uid)
        self.assignee = role
        yield

    def assign(self, team: str, role: str):
        """Lead sets team and assignee in the form and saves."""
        s = self.s("lead")
        s.open_form(TICKET, self.root_id)
        label = REASSIGN_TICKET if self.t()["user_id"] else ASSIGN_TICKET
        uid = self.sim.backend.users[role].uid

        def fill():
            s.many2one(".o_field_widget[name=team_id]", team)
            s.idle()
            s.many2one(".o_field_widget[name=user_id]", config.ROLES[role]["name"])

        self.event(s, label, SAVE, TICKET, self.root_id, pre=fill,
                   post=lambda: self.save_done(s) or (
                       None if (self.t()["user_id"] or [0])[0] == uid else "assignee not saved"))
        self.assignee = role
        yield

    def wait_cycle(self):
        """Assignee asks the customer; the customer answers (or not).
        Returns False if the ticket was cancelled for lack of an answer."""
        pl = self.plan
        yield from self.step(self.assignee, "Awaiting")
        if pl["customer_silent"]:
            yield from self.step("lead", "Cancelled")
            return False
        yield from self.reply("Here are the details you asked for.")
        yield from self.step(self.assignee, "In Progress")
        return True

    # -- orchestration -------------------------------------------------------
    def run(self):
        pl = self.plan
        yield from self.submit()
        if pl["withdraw_early"]:
            yield from self.portal_close("Cancelled")
            return
        if pl["duplicate"]:
            yield from self.step("agent", "Rejected")
            return
        if pl["triage_by_lead"]:
            yield from self.assign("First Level", "agent")
        else:
            yield from self.assign_to_me("agent")
        yield from self.step(self.assignee, "In Progress")
        if pl["handover_to_lead"]:
            yield from self.assign("First Level", "lead")
        if pl["awaiting"]:
            if not (yield from self.wait_cycle()):
                return
            if pl["second_wait"]:
                if not (yield from self.wait_cycle()):
                    return
        if pl["escalate"]:
            yield from self.step(self.assignee, "Escalated")
            yield from self.assign("Second Level", "specialist")
            yield from self.step("specialist", "In Progress")
            if pl["specialist_waits"]:
                if not (yield from self.wait_cycle()):
                    return
        if pl["withdraw_late"]:
            if (yield from self.portal_close("Cancelled")):
                return
        if pl["wrong_close"]:
            # clicked Done instead of Resolved, corrected right away
            self.move(self.assignee, "Done")
            self.move(self.assignee, "Resolved")
            yield
        else:
            yield from self.step(self.assignee, "Resolved")
        outcome = pl["after_resolve"]
        if outcome == "reopen":
            yield from self.reply("Unfortunately the problem is back.")
            yield from self.step(self.assignee, "In Progress")
            yield from self.step(self.assignee, "Resolved")
            outcome = "confirm"
        if outcome == "confirm" and (yield from self.portal_close("Done")):
            return
        # no answer from the customer (or the portal button is gone): the lead closes
        yield from self.step("lead", "Done")
