"""Scenario 1: purchase-to-pay (Odoo Purchase + Inventory + Invoicing).

One case = one procurement, from RFQ to payment of the vendor bill.
"""
from __future__ import annotations

import datetime as dt

from . import config
from .core import MOVE, PICKING, SAVE, Backend, BaseCase, Scenario, move_facts, picking_facts

PO = "purchase.order"

CREATE_RFQ = "Create RFQ"
CHANGE_ORDER = "Change Order"
COMPOSE_RFQ_EMAIL = "Compose RFQ Email"
SEND_RFQ = "Send RFQ"
COMPOSE_PO_EMAIL = "Compose PO Email"
SEND_PO = "Send PO"
DISCARD_EMAIL = "Discard Email"
CONFIRM_ORDER = "Confirm Order"
APPROVE_ORDER = "Approve Order"
CANCEL_ORDER = "Cancel Order"
SET_ORDER_TO_DRAFT = "Set Order to Draft"
LOCK_ORDER = "Lock Order"
UNLOCK_ORDER = "Unlock Order"
CREATE_BILL = "Create Bill"
SET_RECEIVED_QTY = "Set Received Quantity"
VALIDATE_RECEIPT = "Validate Receipt"
CANCEL_RECEIPT = "Cancel Receipt"
CREATE_BACKORDER = "Create Backorder"
NO_BACKORDER = "No Backorder"
DISCARD_BACKORDER = "Discard Backorder"
COMPLETE_BILL = "Complete Bill"
CONFIRM_BILL = "Confirm Bill"
CANCEL_BILL = "Cancel Bill"
RESET_BILL = "Reset Bill to Draft"
REGISTER_PAYMENT = "Register Payment"
CREATE_PAYMENT = "Create Payment"
DISCARD_PAYMENT = "Discard Payment"

RFQ_STATUS = {"RFQ", "RFQ Sent"}  # status-bar captions of a not yet confirmed order
RECEIPT_LABELS = {"set_qty": SET_RECEIVED_QTY, "validate": VALIDATE_RECEIPT,
                  "create_backorder": CREATE_BACKORDER, "no_backorder": NO_BACKORDER,
                  "discard_backorder": DISCARD_BACKORDER}
PAY_LABELS = {"register": REGISTER_PAYMENT, "create": CREATE_PAYMENT, "discard": DISCARD_PAYMENT}


def _is_rfq(snap: dict) -> bool:
    return snap.get("status") in RFQ_STATUS


class PurchaseToPay(Scenario):
    name = "purchase_to_pay"
    prefix = "PR"
    roles = ("requester", "buyer", "manager", "warehouse", "accountant")
    ROOT = PO
    CREATE = CREATE_RFQ
    SHORT = {PO: "po", PICKING: "receipt", MOVE: "bill"}
    FORM_BUTTONS = {
        (PO, "button_confirm"): CONFIRM_ORDER,
        (PO, "button_approve"): APPROVE_ORDER,
        (PO, "button_cancel"): CANCEL_ORDER,
        (PO, "button_draft"): SET_ORDER_TO_DRAFT,
        (PO, "button_done"): LOCK_ORDER,
        (PO, "button_unlock"): UNLOCK_ORDER,
        (PO, "action_create_invoice"): CREATE_BILL,
        (PO, "action_rfq_send"): lambda snap: COMPOSE_RFQ_EMAIL if _is_rfq(snap) else COMPOSE_PO_EMAIL,
        (PICKING, "button_validate"): VALIDATE_RECEIPT,
        (PICKING, "action_cancel"): CANCEL_RECEIPT,
        (MOVE, "action_post"): CONFIRM_BILL,
        (MOVE, "button_cancel"): CANCEL_BILL,
        (MOVE, "button_draft"): RESET_BILL,
        (MOVE, "action_register_payment"): REGISTER_PAYMENT,
    }
    EDIT_FIELDS = {
        (PO, "order_line"): CHANGE_ORDER,
        (PICKING, "move_ids_without_package"): SET_RECEIVED_QTY,
        (MOVE, "invoice_date"): COMPLETE_BILL,
    }
    WIZARDS = {"action_send_mail": "mail", "process": "backorder", "action_create_payments": "payment"}
    WIZARD_BUTTONS = {
        ("mail", "action_send_mail"): lambda snap: SEND_RFQ if _is_rfq(snap) else SEND_PO,
        ("backorder", "process"): CREATE_BACKORDER,
        ("backorder", "process_cancel_backorder"): NO_BACKORDER,
        ("payment", "action_create_payments"): CREATE_PAYMENT,
    }
    WIZARD_DISCARD = {"mail": DISCARD_EMAIL, "backorder": DISCARD_BACKORDER, "payment": DISCARD_PAYMENT}
    VOCABULARY = (
        CREATE_RFQ, CHANGE_ORDER, COMPOSE_RFQ_EMAIL, SEND_RFQ, COMPOSE_PO_EMAIL, SEND_PO, DISCARD_EMAIL,
        CONFIRM_ORDER, APPROVE_ORDER, CANCEL_ORDER, SET_ORDER_TO_DRAFT, LOCK_ORDER, UNLOCK_ORDER,
        CREATE_BILL, SET_RECEIVED_QTY, VALIDATE_RECEIPT, CANCEL_RECEIPT, CREATE_BACKORDER, NO_BACKORDER,
        DISCARD_BACKORDER, COMPLETE_BILL, CONFIRM_BILL, CANCEL_BILL, RESET_BILL, REGISTER_PAYMENT,
        CREATE_PAYMENT, DISCARD_PAYMENT)
    CAUSES = (
        ("bill-date-missing", "only_gui", CONFIRM_BILL,
         "Odoo shows Confirm on every draft bill; action_post refuses while the bill date is empty."),
        ("cancel-after-receipt-or-bill", "only_gui", CANCEL_ORDER,
         "The order form shows Cancel for every confirmed order; button_cancel refuses once goods "
         "were received or a bill is posted."),
        ("nothing-to-bill", "only_gui", CREATE_BILL,
         "The order form shows Create Bill for every confirmed order; action_create_invoice refuses "
         "when no line is invoiceable (nothing received yet, or fully billed)."),
        ("unlock-manager-only-in-view", "only_backend", UNLOCK_ORDER,
         "The Unlock button is shown to Purchase Administrators only; button_unlock itself has no "
         "group check."),
        ("empty-receipt", "only_gui", VALIDATE_RECEIPT,
         "Validate is shown on every open receipt; button_validate refuses when all quantities are 0."),
    )
    TRACKED = {PO: [(0, "state", "selection")], PICKING: [(0, "state", "selection")],
               MOVE: [(0, "state", "selection"), (1, "payment_state", "untracked")]}

    # -- backend -------------------------------------------------------------
    def facts(self, be: Backend, model: str, rec_id: int) -> dict:
        a = be.admin
        if model == PO:
            f = a.read(PO, [rec_id], ["name", "state", "invoice_status", "amount_total",
                                      "order_line", "invoice_ids", "picking_ids"])[0]
            bills = a.read(MOVE, f["invoice_ids"], ["state"]) if f["invoice_ids"] else []
            f["has_open_bill"] = any(b["state"] not in ("draft", "cancel") for b in bills)
            f["has_done_receipt"] = bool(f["picking_ids"]) and a.call(
                "stock.move", "search_count",
                [("picking_id", "in", f["picking_ids"]), ("state", "=", "done")]) > 0
            return f
        if model == PICKING:
            return picking_facts(be, rec_id)
        return move_facts(be, rec_id)

    def state_label(self, model: str, f: dict) -> str:
        return f"{f['state']}/{f['payment_state']}" if model == MOVE else f["state"]

    def case_docs(self, be: Backend, root_id: int) -> list[tuple[str, int]]:
        f = be.admin.read(PO, [root_id], ["picking_ids", "invoice_ids"])[0]
        return ([(PO, root_id)] + [(PICKING, i) for i in sorted(f["picking_ids"])]
                + [(MOVE, i) for i in sorted(f["invoice_ids"])])

    def rules(self, be: Backend, role: str, model: str | None, f: dict | None,
              wizard: str | None = None) -> set[str]:
        """Activities the server would accept from `role` on this document.

        Transcribed from Odoo 17: purchase/models/purchase.py, purchase_stock,
        stock/models/stock_picking.py, account/models/account_move.py.
        Methods without a guard on the server (e.g. `button_draft`) are
        limited to the source states of their intended transition.
        """
        r = lambda m, op: be.right(role, m, op)  # noqa: E731
        billing = be.group(role, "account.group_account_invoice")
        out: set[str] = set()
        if model in (None, PO) and r(PO, "create") and not wizard:
            out.add(CREATE_RFQ)
        if f is None:
            return out
        st = f["state"]
        if model == PO:
            w = r(PO, "write")
            if wizard == "mail":
                if r("mail.compose.message", "create") and w:
                    out |= {SEND_RFQ if st in ("draft", "sent") else SEND_PO, DISCARD_EMAIL}
                return out
            if not w:
                return out
            if st not in ("done", "cancel"):
                out.add(CHANGE_ORDER)
            if r("mail.compose.message", "create"):
                if st in ("draft", "sent"):
                    out.add(COMPOSE_RFQ_EMAIL)
                elif st == "purchase":
                    out.add(COMPOSE_PO_EMAIL)
            if st in ("draft", "sent"):
                out.add(CONFIRM_ORDER)
            if st == "to approve" and (
                    be.group(role, "purchase.group_purchase_manager")
                    or be.company["po_double_validation"] != "two_step"
                    or f["amount_total"] < be.company["po_double_validation_amount"]):
                out.add(APPROVE_ORDER)
            # button_cancel refuses once a bill is posted or goods were received
            if st in ("draft", "sent", "to approve", "purchase") \
                    and not f["has_open_bill"] and not f["has_done_receipt"]:
                out.add(CANCEL_ORDER)
            if st == "cancel":
                out.add(SET_ORDER_TO_DRAFT)
            if st == "purchase":
                out.add(LOCK_ORDER)
            if st == "done":
                out.add(UNLOCK_ORDER)
            # action_create_invoice raises "There is no invoiceable line" otherwise
            if st in ("purchase", "done") and f["invoice_status"] == "to invoice" and r(MOVE, "create"):
                out.add(CREATE_BILL)
        elif model == PICKING:
            w = r(PICKING, "write")
            if wizard == "backorder":
                if r("stock.backorder.confirmation", "create") and w and f["short"]:
                    out |= {CREATE_BACKORDER, NO_BACKORDER, DISCARD_BACKORDER}
                return out
            if not w:
                return out
            if st not in ("done", "cancel"):
                out |= {SET_RECEIVED_QTY, CANCEL_RECEIPT}
            if st in ("assigned", "confirmed") and f["any_qty"]:
                out.add(VALIDATE_RECEIPT)
        elif model == MOVE:
            w = r(MOVE, "write")
            if wizard == "payment":
                if r("account.payment.register", "create") and billing:
                    out |= {CREATE_PAYMENT, DISCARD_PAYMENT}
                return out
            if not w:
                return out
            if st == "draft":
                out |= {COMPLETE_BILL, CANCEL_BILL}
                # action_post: needs Billing group, a bill date and at least one line
                if billing and f["invoice_date"] and f["invoice_line_ids"]:
                    out.add(CONFIRM_BILL)
            if st in ("posted", "cancel") and billing:
                out.add(RESET_BILL)
            if st == "posted" and f["payment_state"] in ("not_paid", "partial") \
                    and billing and r("account.payment.register", "create"):
                out.add(REGISTER_PAYMENT)
        return out


SCENARIO = PurchaseToPay()


class Case(BaseCase):
    sc = SCENARIO

    def draw_plan(self) -> dict:
        r = self.rng
        kind = r.choices(["receive", "purchase", "service"], [0.55, 0.25, 0.20])[0]
        pool = [p for p in config.PRODUCTS
                if (p["kind"] == "service") == (kind == "service")
                and (kind == "service" or p["policy"] == kind)]
        n = min(len(pool), r.choices([1, 2, 3], [0.55, 0.3, 0.15])[0])
        lines = []
        for p in r.sample(pool, n):
            top = max(2, int(6500 / p["price"]))
            lines.append({"product": p["name"], "qty": r.randint(2, top) if top > 2 else r.randint(1, 3)})
        return {
            "kind": kind,
            "vendor": r.choice(config.VENDORS)["name"],
            "lines": lines,
            "cancel_draft": r.random() < 0.05,
            "buyer_edit": r.random() < 0.15,
            "send_rfq": r.random() < 0.85,
            "composer_discard": r.random() < 0.05,
            "resend_after_discard": r.random() < 0.6,
            "manager_rejects": r.random() < 0.15,
            "rework_after_reject": r.random() < 0.65,
            "cancel_after_confirm": r.random() < 0.04,
            "premature_bill": r.random() < 0.06,
            "bill_before_receipt": r.random() < 0.3,
            "receipt_mode": r.choices(["full", "backorder", "no_backorder"], [0.80, 0.12, 0.08])[0],
            "partial_fraction": r.uniform(0.3, 0.8),
            "wrong_qty": r.random() < 0.04,
            "backorder_discard": r.random() < 0.06,
            "split_billing": r.random() < 0.5,
            "forgot_bill_date": r.random() < 0.10,
            "split_bill_session": r.random() < 0.3,
            "reset_bill": r.random() < 0.05,
            "payment_discard": r.random() < 0.05,
            "skip_payment": r.random() < 0.05,
            "lock": r.random() < 0.10,
            # drawn after the original flags so that earlier choices keep their values
            "send_po": r.random() < 0.10,
            "receipt_cancelled": r.random() < 0.05,
            "cancel_bill": r.random() < 0.05,
            "unlock": r.random() < 0.5,
            "empty_receipt": r.random() < 0.04,
        }

    def po(self) -> dict:
        return self.root()

    def state_is(self, *states):
        return lambda: self.po()["state"] in states

    def po_button(self, s, activity: str, name: str, done) -> bool:
        return self.button(s, activity, PO, self.root_id, name, done)

    # -- requester -----------------------------------------------------------
    def request(self):
        s = self.s("requester")
        s.open_list("purchase.purchase_rfq")

        def fill_and_save():
            p = s.page
            p.wait_for_selector(".o_form_view .o_field_widget[name=partner_id] input")
            s.idle()
            s.many2one(".o_field_widget[name=partner_id]", self.plan["vendor"])
            p.locator(".o_field_widget[name=partner_ref] input").fill(self.case_id)
            for line in self.plan["lines"]:
                p.locator(".o_field_widget[name=order_line] .o_field_x2many_list_row_add a").first.click()
                s.many2one(".o_field_widget[name=order_line] tr.o_selected_row td[name=product_id]",
                           line["product"])
                s.idle()
                qty = p.locator(".o_field_widget[name=order_line] tr.o_selected_row td[name=product_qty] input")
                qty.fill(str(line["qty"]))
                qty.press("Tab")
                s.idle(150)
            p.locator(SAVE).locator("visible=true").first.click()
            s.idle()
            self.root_id = s.wait_for(s.record_id, what="saved RFQ id")
            return None

        self.event(s, CREATE_RFQ, ".o_list_button_add", PO, None, post=fill_and_save)
        yield

    # -- buyer ---------------------------------------------------------------
    def change_order(self, s, factor: float) -> None:
        line = self.admin.read("purchase.order.line", self.po()["order_line"][:1], ["product_qty"])[0]
        new_qty = max(1, int(round(line["product_qty"] * factor)))
        if new_qty == int(line["product_qty"]):
            new_qty += 1
        self.set_cell_event(s, CHANGE_ORDER, PO, self.root_id, "order_line", "product_qty", new_qty)

    def rfq_mail(self, s, discard: bool) -> None:
        self.mail_dialog(s, PO, self.root_id, "action_rfq_send", COMPOSE_RFQ_EMAIL, SEND_RFQ,
                         DISCARD_EMAIL, discard, self.state_is("sent"))

    def buyer_rfq(self):
        """Returns False if the RFQ was cancelled before confirmation."""
        s = self.s("buyer")
        pl = self.plan
        s.open_form(PO, self.root_id)
        if pl["cancel_draft"]:
            self.po_button(s, CANCEL_ORDER, "button_cancel", self.state_is("cancel"))
            yield
            return False
        if pl["buyer_edit"]:
            self.change_order(s, self.rng.choice([0.5, 0.8, 1.2, 1.5]))
        if pl["send_rfq"]:
            if pl["composer_discard"]:
                self.rfq_mail(s, discard=True)
                if pl["resend_after_discard"]:
                    self.rfq_mail(s, discard=False)
            else:
                self.rfq_mail(s, discard=False)
            yield  # waiting for the vendor's answer
            s.open_form(PO, self.root_id)
        self.po_button(s, CONFIRM_ORDER, "button_confirm", self.state_is("to approve", "purchase"))
        yield
        return True

    def approval(self):
        """Returns True once the order is confirmed, False if it was rejected for good."""
        rejected_once = False
        while self.po()["state"] == "to approve":
            m = self.s("manager")
            m.open_form(PO, self.root_id)
            if self.plan["manager_rejects"] and not rejected_once:
                rejected_once = True
                self.po_button(m, CANCEL_ORDER, "button_cancel", self.state_is("cancel"))
                yield
                if not self.plan["rework_after_reject"]:
                    return False
                b = self.s("buyer")
                b.open_form(PO, self.root_id)
                self.po_button(b, SET_ORDER_TO_DRAFT, "button_draft", self.state_is("draft"))
                self.change_order(b, self.rng.choice([0.3, 0.5, 0.7]))
                self.po_button(b, CONFIRM_ORDER, "button_confirm", self.state_is("to approve", "purchase"))
                yield
            else:
                self.po_button(m, APPROVE_ORDER, "button_approve", self.state_is("purchase"))
                yield
        return self.po()["state"] == "purchase"

    def send_po(self):
        s = self.s("buyer")
        s.open_form(PO, self.root_id)
        self.mail_dialog(s, PO, self.root_id, "action_rfq_send", COMPOSE_PO_EMAIL, SEND_PO,
                         DISCARD_EMAIL, False, lambda: True)
        yield

    def cancel_order(self):
        s = self.s("buyer")
        s.open_form(PO, self.root_id)
        self.po_button(s, CANCEL_ORDER, "button_cancel", self.state_is("cancel"))
        yield

    def lock(self):
        s = self.s("buyer")
        s.open_form(PO, self.root_id)
        self.po_button(s, LOCK_ORDER, "button_done", self.state_is("done"))
        yield
        if self.plan["unlock"]:
            m = self.s("manager")
            m.open_form(PO, self.root_id)
            self.po_button(m, UNLOCK_ORDER, "button_unlock", self.state_is("purchase"))
            yield

    # -- warehouse -----------------------------------------------------------
    def open_receipts(self) -> list[int]:
        return self.admin.search(PICKING, [("purchase_id", "=", self.root_id),
                                           ("state", "=", "assigned")], order="id")

    def receive(self, pid: int, mode: str, first: bool):
        pl = self.plan
        yield from self.transfer("warehouse", pid, mode, RECEIPT_LABELS,
                                 wrong_qty=pl["wrong_qty"] and first,
                                 zero_qty=pl["empty_receipt"] and first,
                                 backorder_discard=pl["backorder_discard"] and first)

    def receipts(self, first_mode: str):
        first = True
        while True:
            open_ = self.open_receipts()
            if not open_:
                return
            yield from self.receive(open_[0], first_mode if first else "full", first)
            first = False

    def cancel_receipt(self, pid: int):
        s = self.s("warehouse")
        s.open_form(PICKING, pid)
        self.button(s, CANCEL_RECEIPT, PICKING, pid, "action_cancel",
                    lambda: self.facts(PICKING, pid)["state"] == "cancel", confirm=True)
        yield

    # -- accountant ----------------------------------------------------------
    def bill(self, bill_id: int) -> dict:
        return self.facts(MOVE, bill_id)

    def bill_button(self, s, bill_id: int, activity: str, name: str, done) -> bool:
        return self.button(s, activity, MOVE, bill_id, name, done)

    def try_create_bill(self, s) -> int | None:
        before = set(self.po()["invoice_ids"])
        new = lambda: set(self.po()["invoice_ids"]) - before  # noqa: E731
        if not self.po_button(s, CREATE_BILL, "action_create_invoice", lambda: bool(new())):
            return None
        bill_id = new().pop()
        s.page.wait_for_selector(".o_form_view .o_field_widget[name=invoice_date]")
        s.idle()
        self.n_bills = getattr(self, "n_bills", 0) + 1
        return bill_id

    def premature_bill(self):
        s = self.s("accountant")
        s.open_form(PO, self.root_id)
        self.try_create_bill(s)
        yield

    def billing(self):
        """One vendor bill for whatever is invoiceable now: create, complete, confirm, pay."""
        pl = self.plan
        if self.po()["invoice_status"] != "to invoice":
            return
        s = self.s("accountant")
        s.open_form(PO, self.root_id)
        bill_id = self.try_create_bill(s)
        if bill_id is None:
            yield
            return
        first_bill = self.n_bills == 1
        if pl["cancel_bill"] and first_bill:
            # created by mistake: cancel the draft and start over
            self.bill_button(s, bill_id, CANCEL_BILL, "button_cancel",
                             lambda: self.bill(bill_id)["state"] == "cancel")
            yield
            s.open_form(PO, self.root_id)
            bill_id = self.try_create_bill(s)
            if bill_id is None:
                yield
                return
        posted = lambda: self.bill(bill_id)["state"] == "posted"  # noqa: E731
        confirm = lambda: self.bill_button(s, bill_id, CONFIRM_BILL, "action_post", posted)  # noqa: E731
        if pl["forgot_bill_date"] and first_bill:
            confirm()  # Odoo refuses: the bill date is required

        def fill_date():
            inp = s.page.locator(".o_field_widget[name=invoice_date] input").first
            inp.click()
            inp.fill(dt.date.today().strftime("%m/%d/%Y"))
            inp.press("Enter")
            s.idle(150)

        self.event(s, COMPLETE_BILL, SAVE, MOVE, bill_id, pre=fill_date,
                   post=lambda: self.settle(s, lambda: bool(self.bill(bill_id)["invoice_date"])))
        if pl["split_bill_session"]:
            yield
            s.open_form(MOVE, bill_id)
        confirm()
        if pl["reset_bill"] and first_bill:
            self.bill_button(s, bill_id, RESET_BILL, "button_draft",
                             lambda: self.bill(bill_id)["state"] == "draft")
            confirm()
        yield
        if pl["skip_payment"]:
            return
        yield from self.pay("accountant", bill_id, PAY_LABELS,
                            discard_first=pl["payment_discard"] and first_bill)

    # -- orchestration -------------------------------------------------------
    def run(self):
        pl = self.plan
        yield from self.request()
        if not (yield from self.buyer_rfq()):
            return
        if not (yield from self.approval()):
            return
        if pl["cancel_after_confirm"]:
            yield from self.cancel_order()
            return
        if pl["send_po"]:
            yield from self.send_po()
        if pl["kind"] == "service":
            yield from self.billing()
        elif pl["kind"] == "purchase":
            # billed on ordered quantities: receipt and billing are independent
            if pl["bill_before_receipt"]:
                yield from self.interleave(self.receipts(pl["receipt_mode"]), self.billing())
            else:
                yield from self.receipts(pl["receipt_mode"])
                yield from self.billing()
        else:
            # billed on received quantities: nothing to bill before a receipt
            if pl["premature_bill"]:
                yield from self.premature_bill()
            first = self.open_receipts()
            if first and pl["receipt_cancelled"]:
                # the goods never arrive: receipt cancelled, then the order
                yield from self.cancel_receipt(first[0])
                yield from self.cancel_order()
                return
            if first:
                yield from self.receive(first[0], pl["receipt_mode"], True)
            if self.open_receipts() and pl["split_billing"]:
                yield from self.interleave(self.receipts("full"), self.billing())
            else:
                yield from self.receipts("full")
            yield from self.billing()
        if pl["lock"]:
            yield from self.lock()
