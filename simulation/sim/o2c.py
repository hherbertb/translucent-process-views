"""Scenario 2: order-to-cash (Odoo Sales + Inventory + Invoicing).

One case = one customer order, from quotation to payment of the invoice,
optionally followed by a return and a credit note.
"""
from __future__ import annotations

import datetime as dt

from . import config
from .core import MOVE, PICKING, SAVE, Backend, BaseCase, Scenario, move_facts, picking_facts

SO = "sale.order"

CREATE_QUOTATION = "Create Quotation"
REVISE_QUOTATION = "Revise Quotation"
CHANGE_SALES_ORDER = "Change Sales Order"
COMPOSE_QUOTATION_EMAIL = "Compose Quotation Email"
SEND_QUOTATION = "Send Quotation"
COMPOSE_ORDER_EMAIL = "Compose Order Email"
SEND_ORDER_CONFIRMATION = "Send Order Confirmation"
DISCARD_SALES_EMAIL = "Discard Sales Email"
CONFIRM_SALES_ORDER = "Confirm Sales Order"
CANCEL_QUOTATION = "Cancel Quotation"
START_CANCELLATION = "Start Order Cancellation"
CONFIRM_CANCELLATION = "Confirm Order Cancellation"
SEND_CANCELLATION = "Send Cancellation Email"
DISCARD_CANCELLATION = "Discard Order Cancellation"
SET_TO_QUOTATION = "Set to Quotation"
PREPARE_INVOICE = "Prepare Invoice"
CREATE_INVOICE = "Create Invoice"
DISCARD_INVOICE = "Discard Invoice Creation"
SET_DELIVERED_QTY = "Set Delivered Quantity"
VALIDATE_DELIVERY = "Validate Delivery"
CANCEL_DELIVERY = "Cancel Delivery"
CREATE_DELIVERY_BACKORDER = "Create Delivery Backorder"
NO_DELIVERY_BACKORDER = "No Delivery Backorder"
DISCARD_DELIVERY_BACKORDER = "Discard Delivery Backorder"
PREPARE_RETURN = "Prepare Return"
CREATE_RETURN = "Create Return"
DISCARD_RETURN = "Discard Return"
SET_RETURNED_QTY = "Set Returned Quantity"
VALIDATE_RETURN = "Validate Return"
CANCEL_RETURN = "Cancel Return"
SET_INVOICE_DATE = "Set Invoice Date"
CONFIRM_INVOICE = "Confirm Invoice"
CANCEL_INVOICE = "Cancel Invoice"
RESET_INVOICE = "Reset Invoice to Draft"
REGISTER_CUSTOMER_PAYMENT = "Register Customer Payment"
CREATE_CUSTOMER_PAYMENT = "Create Customer Payment"
DISCARD_CUSTOMER_PAYMENT = "Discard Customer Payment"
PREPARE_CREDIT_NOTE = "Prepare Credit Note"
CREATE_CREDIT_NOTE = "Create Credit Note"
DISCARD_CREDIT_NOTE = "Discard Credit Note"
CONFIRM_CREDIT_NOTE = "Confirm Credit Note"
CANCEL_CREDIT_NOTE = "Cancel Credit Note"
RESET_CREDIT_NOTE = "Reset Credit Note to Draft"
REGISTER_REFUND = "Register Refund"
CREATE_REFUND_PAYMENT = "Create Refund Payment"
DISCARD_REFUND_PAYMENT = "Discard Refund Payment"

QUOTATION_STATUS = {"Quotation", "Quotation Sent"}
DELIVERY_LABELS = {"set_qty": SET_DELIVERED_QTY, "validate": VALIDATE_DELIVERY,
                   "create_backorder": CREATE_DELIVERY_BACKORDER, "no_backorder": NO_DELIVERY_BACKORDER,
                   "discard_backorder": DISCARD_DELIVERY_BACKORDER}
PAY_LABELS = {"register": REGISTER_CUSTOMER_PAYMENT, "create": CREATE_CUSTOMER_PAYMENT,
              "discard": DISCARD_CUSTOMER_PAYMENT}
REFUND_LABELS = {"register": REGISTER_REFUND, "create": CREATE_REFUND_PAYMENT,
                 "discard": DISCARD_REFUND_PAYMENT}


def _quotation(snap: dict) -> bool:
    return snap.get("status") in QUOTATION_STATUS


def _credit(snap: dict) -> bool:
    """Credit note on screen? Recognised by the page title (document number / type)."""
    t = snap.get("title") or ""
    return "Credit Note" in t or "RINV/" in t


def _ret(snap: dict) -> bool:
    """Return transfer on screen? Returns are receipts (WH/IN/...)."""
    return "/IN/" in (snap.get("title") or "")


def pick(credit_or_return, other, test):
    return lambda snap: credit_or_return if test(snap) else other


class OrderToCash(Scenario):
    name = "order_to_cash"
    prefix = "SO"
    roles = ("sales", "sales_manager", "warehouse", "accountant")
    ROOT = SO
    CREATE = CREATE_QUOTATION
    SHORT = {SO: "so", PICKING: "transfer", MOVE: "invoice"}
    FORM_BUTTONS = {
        (SO, "action_confirm"): CONFIRM_SALES_ORDER,
        (SO, "action_cancel"): lambda s: CANCEL_QUOTATION if s.get("status") == "Quotation" else START_CANCELLATION,
        (SO, "action_draft"): SET_TO_QUOTATION,
        (SO, "action_quotation_send"): lambda s: COMPOSE_QUOTATION_EMAIL if _quotation(s) else COMPOSE_ORDER_EMAIL,
        (SO, "text:Create Invoice"): PREPARE_INVOICE,
        (PICKING, "button_validate"): pick(VALIDATE_RETURN, VALIDATE_DELIVERY, _ret),
        (PICKING, "action_cancel"): pick(CANCEL_RETURN, CANCEL_DELIVERY, _ret),
        (PICKING, "text:Return"): PREPARE_RETURN,
        (MOVE, "action_post"): pick(CONFIRM_CREDIT_NOTE, CONFIRM_INVOICE, _credit),
        (MOVE, "button_cancel"): pick(CANCEL_CREDIT_NOTE, CANCEL_INVOICE, _credit),
        (MOVE, "button_draft"): pick(RESET_CREDIT_NOTE, RESET_INVOICE, _credit),
        (MOVE, "action_register_payment"): pick(REGISTER_REFUND, REGISTER_CUSTOMER_PAYMENT, _credit),
        (MOVE, "action_reverse"): PREPARE_CREDIT_NOTE,
    }
    EDIT_FIELDS = {
        (SO, "order_line"): lambda s: REVISE_QUOTATION if _quotation(s) else CHANGE_SALES_ORDER,
        (PICKING, "move_ids_without_package"): pick(SET_RETURNED_QTY, SET_DELIVERED_QTY, _ret),
        (MOVE, "invoice_date"): lambda s: None if _credit(s) else SET_INVOICE_DATE,
    }
    WIZARDS = {"action_send_mail": "mail", "process": "backorder", "action_create_payments": "payment",
               "action_send_mail_and_cancel": "cancel", "create_invoices": "invoice",
               "create_returns": "return", "refund_moves": "credit"}
    WIZARD_BUTTONS = {
        ("mail", "action_send_mail"): lambda s: SEND_QUOTATION if _quotation(s) else SEND_ORDER_CONFIRMATION,
        ("backorder", "process"): CREATE_DELIVERY_BACKORDER,
        ("backorder", "process_cancel_backorder"): NO_DELIVERY_BACKORDER,
        ("payment", "action_create_payments"): pick(CREATE_REFUND_PAYMENT, CREATE_CUSTOMER_PAYMENT, _credit),
        ("cancel", "action_cancel"): CONFIRM_CANCELLATION,
        ("cancel", "action_send_mail_and_cancel"): SEND_CANCELLATION,
        ("invoice", "create_invoices"): CREATE_INVOICE,
        ("return", "create_returns"): CREATE_RETURN,
        ("credit", "refund_moves"): CREATE_CREDIT_NOTE,
    }
    WIZARD_DISCARD = {"mail": DISCARD_SALES_EMAIL, "backorder": DISCARD_DELIVERY_BACKORDER,
                      "cancel": DISCARD_CANCELLATION, "invoice": DISCARD_INVOICE,
                      "return": DISCARD_RETURN, "credit": DISCARD_CREDIT_NOTE,
                      "payment": pick(DISCARD_REFUND_PAYMENT, DISCARD_CUSTOMER_PAYMENT, _credit)}
    VOCABULARY = (
        CREATE_QUOTATION, REVISE_QUOTATION, CHANGE_SALES_ORDER, COMPOSE_QUOTATION_EMAIL, SEND_QUOTATION,
        COMPOSE_ORDER_EMAIL, SEND_ORDER_CONFIRMATION, DISCARD_SALES_EMAIL, CONFIRM_SALES_ORDER,
        CANCEL_QUOTATION, START_CANCELLATION, CONFIRM_CANCELLATION, SEND_CANCELLATION,
        DISCARD_CANCELLATION, SET_TO_QUOTATION, PREPARE_INVOICE, CREATE_INVOICE, DISCARD_INVOICE,
        SET_DELIVERED_QTY, VALIDATE_DELIVERY, CANCEL_DELIVERY, CREATE_DELIVERY_BACKORDER,
        NO_DELIVERY_BACKORDER, DISCARD_DELIVERY_BACKORDER, PREPARE_RETURN, CREATE_RETURN, DISCARD_RETURN,
        SET_RETURNED_QTY, VALIDATE_RETURN, CANCEL_RETURN, SET_INVOICE_DATE, CONFIRM_INVOICE,
        CANCEL_INVOICE, RESET_INVOICE, REGISTER_CUSTOMER_PAYMENT, CREATE_CUSTOMER_PAYMENT,
        DISCARD_CUSTOMER_PAYMENT, PREPARE_CREDIT_NOTE, CREATE_CREDIT_NOTE, DISCARD_CREDIT_NOTE,
        CONFIRM_CREDIT_NOTE, CANCEL_CREDIT_NOTE, RESET_CREDIT_NOTE, REGISTER_REFUND,
        CREATE_REFUND_PAYMENT, DISCARD_REFUND_PAYMENT)
    CAUSES = (
        ("nothing-to-invoice", "only_gui", CREATE_INVOICE,
         "The invoice dialog always offers Create Draft Invoice; create_invoices refuses when no "
         "line is invoiceable (delivery-based products before the delivery)."),
        ("invoice-dialog-hidden-when-invoiced", "only_backend", PREPARE_INVOICE,
         "The order form hides Create Invoice once everything is invoiced; the dialog itself can "
         "still be opened on any confirmed order (the server serves it without a guard)."),
        ("empty-delivery", "only_gui", VALIDATE_DELIVERY,
         "Validate is shown on every open delivery; button_validate refuses when all quantities are 0."),
        ("empty-return", "only_gui", VALIDATE_RETURN,
         "Validate is shown on every open return; button_validate refuses when all quantities are 0."),
    )
    NEVER_EXECUTED = (CANCEL_RETURN, CANCEL_CREDIT_NOTE, RESET_CREDIT_NOTE, DISCARD_REFUND_PAYMENT,
                      SET_RETURNED_QTY)
    UNTRACKED = {
        (SO, "state", "draft", "sent"):
            "sale/models/sale_order.py:1499 marks the quotation as sent with tracking_disable=True",
        (SO, "state", "cancel", "draft"):
            "action_draft (Set to Quotation) leaves no tracking value in Odoo 17 (observed)",
    }
    TRACKED = {SO: [(0, "state", "selection")], PICKING: [(0, "state", "selection")],
               MOVE: [(0, "state", "selection"), (1, "payment_state", "untracked")]}

    # -- backend -------------------------------------------------------------
    def facts(self, be: Backend, model: str, rec_id: int) -> dict:
        if model == SO:
            return be.admin.read(SO, [rec_id], ["name", "state", "locked", "invoice_status",
                                                "amount_total", "order_line", "invoice_ids",
                                                "picking_ids"])[0]
        if model == PICKING:
            return picking_facts(be, rec_id)
        return move_facts(be, rec_id)

    def state_label(self, model: str, f: dict) -> str:
        return f"{f['state']}/{f['payment_state']}" if model == MOVE else f["state"]

    def case_docs(self, be: Backend, root_id: int) -> list[tuple[str, int]]:
        f = be.admin.read(SO, [root_id], ["picking_ids", "invoice_ids"])[0]
        return ([(SO, root_id)] + [(PICKING, i) for i in sorted(f["picking_ids"])]
                + [(MOVE, i) for i in sorted(f["invoice_ids"])])

    def rules(self, be: Backend, role: str, model: str | None, f: dict | None,
              wizard: str | None = None) -> set[str]:
        """Transcribed from Odoo 17: sale/models/sale_order.py, sale/wizard,
        sale_stock, stock/models/stock_picking.py, account/models/account_move.py."""
        r = lambda m, op: be.right(role, m, op)  # noqa: E731
        billing = be.group(role, "account.group_account_invoice")
        out: set[str] = set()
        if model in (None, SO) and r(SO, "create") and not wizard:
            out.add(CREATE_QUOTATION)
        if f is None:
            return out
        st = f["state"]
        if model == SO:
            w = be.can_write(role, SO, f["_id"])
            quotation = st in ("draft", "sent")
            if wizard == "mail":
                if w and r("mail.compose.message", "create"):
                    out |= {SEND_QUOTATION if quotation else SEND_ORDER_CONFIRMATION, DISCARD_SALES_EMAIL}
                return out
            if wizard == "cancel":
                if w and r("sale.order.cancel", "create") and st in ("sent", "sale") and not f["locked"]:
                    out |= {CONFIRM_CANCELLATION, SEND_CANCELLATION, DISCARD_CANCELLATION}
                return out
            if wizard == "invoice":
                if r("sale.advance.payment.inv", "create"):
                    out.add(DISCARD_INVOICE)
                    # create_invoices raises "Cannot create an invoice" when nothing is invoiceable
                    if st == "sale" and f["invoice_status"] == "to invoice":
                        out.add(CREATE_INVOICE)
                return out
            if not w:
                return out
            mail = r("mail.compose.message", "create")
            if quotation:
                out |= {REVISE_QUOTATION, CONFIRM_SALES_ORDER}
                if mail:
                    out.add(COMPOSE_QUOTATION_EMAIL)
            if st == "draft":
                out.add(CANCEL_QUOTATION)
            if st in ("sent", "sale") and not f["locked"] and r("sale.order.cancel", "create"):
                out.add(START_CANCELLATION)
            if st == "sale" and not f["locked"]:
                out.add(CHANGE_SALES_ORDER)
            if st == "sale":
                if mail:
                    out.add(COMPOSE_ORDER_EMAIL)
                if r("sale.advance.payment.inv", "create"):
                    out.add(PREPARE_INVOICE)
            if st == "cancel":
                out.add(SET_TO_QUOTATION)
        elif model == PICKING:
            w = r(PICKING, "write")
            ret = f["picking_type_code"] == "incoming"
            if wizard == "backorder":
                if r("stock.backorder.confirmation", "create") and w and f["short"]:
                    out |= {CREATE_DELIVERY_BACKORDER, NO_DELIVERY_BACKORDER, DISCARD_DELIVERY_BACKORDER}
                return out
            if wizard == "return":
                if r("stock.return.picking", "create") and w and st == "done":
                    out |= {CREATE_RETURN, DISCARD_RETURN}
                return out
            if not w:
                return out
            if st not in ("done", "cancel"):
                out |= {SET_RETURNED_QTY, CANCEL_RETURN} if ret else {SET_DELIVERED_QTY, CANCEL_DELIVERY}
            if st in ("assigned", "confirmed") and f["any_qty"]:
                out.add(VALIDATE_RETURN if ret else VALIDATE_DELIVERY)
            if st == "done" and r("stock.return.picking", "create"):
                out.add(PREPARE_RETURN)
        elif model == MOVE:
            w = r(MOVE, "write")
            credit = f["move_type"] == "out_refund"
            can_pay = billing and r("account.payment.register", "create")
            if wizard == "payment":
                if can_pay:
                    out |= ({CREATE_REFUND_PAYMENT, DISCARD_REFUND_PAYMENT} if credit
                            else {CREATE_CUSTOMER_PAYMENT, DISCARD_CUSTOMER_PAYMENT})
                return out
            if wizard == "credit":
                if billing and r("account.move.reversal", "create") and st == "posted":
                    out |= {CREATE_CREDIT_NOTE, DISCARD_CREDIT_NOTE}
                return out
            if not w:
                return out
            if st == "draft":
                out.add(CANCEL_CREDIT_NOTE if credit else CANCEL_INVOICE)
                if not credit:
                    out.add(SET_INVOICE_DATE)
                # customer documents get today's date on posting: no date needed
                if billing and f["invoice_line_ids"]:
                    out.add(CONFIRM_CREDIT_NOTE if credit else CONFIRM_INVOICE)
            if st in ("posted", "cancel") and billing:
                out.add(RESET_CREDIT_NOTE if credit else RESET_INVOICE)
            if st == "posted" and f["payment_state"] in ("not_paid", "partial") and can_pay:
                out.add(REGISTER_REFUND if credit else REGISTER_CUSTOMER_PAYMENT)
            if st == "posted" and not credit and billing and r("account.move.reversal", "create"):
                out.add(PREPARE_CREDIT_NOTE)
        return out


SCENARIO = OrderToCash()


class Case(BaseCase):
    sc = SCENARIO

    def draw_plan(self) -> dict:
        r = self.rng
        kind = r.choices(["delivery", "order", "service"], [0.50, 0.25, 0.25])[0]
        pool = [p for p in config.SALE_PRODUCTS
                if (p["kind"] == "service") == (kind == "service")
                and (kind == "service" or p["policy"] == kind)]
        n = min(len(pool), r.choices([1, 2, 3], [0.55, 0.3, 0.15])[0])
        lines = []
        for p in r.sample(pool, n):
            top = max(2, int(7000 / p["price"]))
            lines.append({"product": p["name"], "qty": r.randint(2, top) if top > 2 else r.randint(1, 3)})
        return {
            "kind": kind,
            "customer": r.choice(config.CUSTOMERS)["name"],
            "lines": lines,
            "cancel_quotation": r.random() < 0.05,
            "revise": r.random() < 0.15,
            "send": r.random() < 0.85,
            "composer_discard": r.random() < 0.04,
            "resend": r.random() < 0.10,
            "lost": r.random() < 0.06,
            "reopen_lost": r.random() < 0.6,
            "send_confirmation": r.random() < 0.10,
            "change_after_confirm": r.random() < 0.05,
            "cancel_after_confirm": r.random() < 0.05,
            "cancel_dialog_discard": r.random() < 0.25,
            "cancel_with_email": r.random() < 0.35,
            "premature_invoice": r.random() < 0.08,
            "invoice_before_delivery": r.random() < 0.3,
            "delivery_mode": r.choices(["full", "backorder", "no_backorder"], [0.75, 0.15, 0.10])[0],
            "partial_fraction": r.uniform(0.3, 0.8),
            "wrong_qty": r.random() < 0.04,
            "empty_delivery": r.random() < 0.04,
            "backorder_discard": r.random() < 0.15,
            "delivery_cancelled": r.random() < 0.05,
            "split_invoicing": r.random() < 0.5,
            "invoice_by": r.choice(["sales", "accountant"]),
            "invoice_dialog_discard": r.random() < 0.04,
            "set_invoice_date": r.random() < 0.08,
            "cancel_invoice": r.random() < 0.05,
            "reset_invoice": r.random() < 0.08,
            "split_invoice_session": r.random() < 0.3,
            "payment_discard": r.random() < 0.04,
            "skip_payment": r.random() < 0.04,
            "return": r.random() < 0.15,
            "return_discard": r.random() < 0.3,
            "credit_discard": r.random() < 0.2,
            "refund": r.random() < 0.6,
        }

    def so(self) -> dict:
        return self.root()

    def state_is(self, *states):
        return lambda: self.so()["state"] in states

    def so_button(self, s, activity: str, name: str, done, wizard=None) -> bool:
        return self.button(s, activity, SO, self.root_id, name, done, wizard=wizard)

    def owner(self) -> str:
        """Who confirms: by convention the manager for large quotations."""
        return "sales_manager" if self.so()["amount_total"] >= config.SALES_REVIEW_THRESHOLD else "sales"

    # -- quotation -----------------------------------------------------------
    def create_quotation(self):
        s = self.s("sales")
        s.open_list("sale.action_quotations_with_onboarding")

        def fill_and_save():
            p = s.page
            p.wait_for_selector(".o_form_view .o_field_widget[name=partner_id] input")
            s.idle()
            s.many2one(".o_field_widget[name=partner_id]", self.plan["customer"])
            s.idle()
            for line in self.plan["lines"]:
                p.locator(".o_field_widget[name=order_line] .o_field_x2many_list_row_add a").first.click()
                s.many2one(".o_field_widget[name=order_line] tr.o_selected_row "
                           ":is(td[name=product_template_id], td[name=product_id])", line["product"])
                s.idle()
                qty = p.locator(".o_field_widget[name=order_line] tr.o_selected_row "
                                "td[name=product_uom_qty] input")
                qty.fill(str(line["qty"]))
                qty.press("Tab")
                s.idle(150)
                # click a neutral spot: closes a lingering product dropdown and
                # commits the row before the next "Add a product"
                p.locator(".o_form_view .o_notebook .nav-link.active").first.click()
                s.idle(150)
            p.locator(SAVE).locator("visible=true").first.click()
            s.idle()
            self.root_id = s.wait_for(s.record_id, what="saved quotation id")
            # the customer reference carries the case id so a case can be found in the GUI
            self.admin.write(SO, [self.root_id], {"client_order_ref": self.case_id})
            return None

        self.event(s, CREATE_QUOTATION, ".o_list_button_add", SO, None, post=fill_and_save)
        yield

    def change_lines(self, s, activity: str, factor: float) -> None:
        line = self.admin.read("sale.order.line", self.so()["order_line"][:1], ["product_uom_qty"])[0]
        new_qty = max(1, int(round(line["product_uom_qty"] * factor)))
        if new_qty == int(line["product_uom_qty"]):
            new_qty += 1
        self.set_cell_event(s, activity, SO, self.root_id, "order_line", "product_uom_qty", new_qty)

    def quotation_mail(self, s, discard: bool) -> None:
        self.mail_dialog(s, SO, self.root_id, "action_quotation_send", COMPOSE_QUOTATION_EMAIL,
                         SEND_QUOTATION, DISCARD_SALES_EMAIL, discard, self.state_is("sent"))

    def cancellation(self, s) -> None:
        """Cancel a sent quotation or a confirmed order through Odoo's dialog."""
        pl = self.plan
        up = lambda: s.page.locator(".modal button[name=action_send_mail_and_cancel]").is_visible()  # noqa: E731
        start = lambda: self.so_button(s, START_CANCELLATION, "action_cancel", up)  # noqa: E731
        start()
        s.idle(400)
        if pl["cancel_dialog_discard"]:
            self.discard(s, DISCARD_CANCELLATION, SO, self.root_id, "cancel")
            start()
            s.idle(400)
        cancelled = lambda: not s.modal_open() and self.so()["state"] == "cancel"  # noqa: E731
        if pl["cancel_with_email"]:
            self.so_button(s, SEND_CANCELLATION, "action_send_mail_and_cancel", cancelled, wizard="cancel")
        else:
            self.so_button(s, CONFIRM_CANCELLATION, "action_cancel", cancelled, wizard="cancel")

    def quotation(self):
        """Returns False if the quotation never became an order."""
        pl = self.plan
        s = self.s("sales")
        s.open_form(SO, self.root_id)
        if pl["cancel_quotation"]:
            self.so_button(s, CANCEL_QUOTATION, "action_cancel", self.state_is("cancel"))
            yield
            return False
        if pl["revise"]:
            self.change_lines(s, REVISE_QUOTATION, self.rng.choice([0.5, 0.8, 1.2, 1.5]))
        if pl["send"]:
            if pl["composer_discard"]:
                self.quotation_mail(s, discard=True)
            self.quotation_mail(s, discard=False)
            yield  # waiting for the customer
            if pl["resend"]:
                # the customer asks for a change: revise and send again
                s.open_form(SO, self.root_id)
                self.change_lines(s, REVISE_QUOTATION, self.rng.choice([0.6, 0.8, 1.25]))
                self.quotation_mail(s, discard=False)
                yield
            if pl["lost"]:
                # the customer declines
                s.open_form(SO, self.root_id)
                self.cancellation(s)
                yield
                if not pl["reopen_lost"]:
                    return False
                s.open_form(SO, self.root_id)
                self.so_button(s, SET_TO_QUOTATION, "action_draft", self.state_is("draft"))
                self.change_lines(s, REVISE_QUOTATION, self.rng.choice([0.5, 0.7]))
                yield
        c = self.s(self.owner())
        c.open_form(SO, self.root_id)
        self.so_button(c, CONFIRM_SALES_ORDER, "action_confirm", self.state_is("sale"))
        yield
        return True

    def after_confirmation(self):
        """Returns False if the order was cancelled."""
        pl = self.plan
        if pl["send_confirmation"]:
            s = self.s("sales")
            s.open_form(SO, self.root_id)
            self.mail_dialog(s, SO, self.root_id, "action_quotation_send", COMPOSE_ORDER_EMAIL,
                             SEND_ORDER_CONFIRMATION, DISCARD_SALES_EMAIL, False, lambda: True)
            yield
        if pl["change_after_confirm"]:
            m = self.s("sales_manager")
            m.open_form(SO, self.root_id)
            self.change_lines(m, CHANGE_SALES_ORDER, self.rng.choice([1.2, 1.5, 2.0]))
            yield
        if pl["cancel_after_confirm"]:
            m = self.s("sales_manager")
            m.open_form(SO, self.root_id)
            self.cancellation(m)
            yield
            return False
        return True

    # -- delivery ------------------------------------------------------------
    def open_transfers(self, code: str) -> list[int]:
        ids = self.so()["picking_ids"]
        return self.admin.search(PICKING, [("id", "in", ids), ("state", "=", "assigned"),
                                           ("picking_type_code", "=", code)], order="id")

    def deliver(self, pid: int, mode: str, first: bool):
        pl = self.plan
        yield from self.transfer("warehouse", pid, mode, DELIVERY_LABELS,
                                 wrong_qty=pl["wrong_qty"] and first,
                                 zero_qty=pl["empty_delivery"] and first,
                                 backorder_discard=pl["backorder_discard"] and first)

    def deliveries(self, first_mode: str):
        first = True
        while True:
            open_ = self.open_transfers("outgoing")
            if not open_:
                return
            yield from self.deliver(open_[0], first_mode if first else "full", first)
            first = False

    # -- invoice -------------------------------------------------------------
    def inv(self, move_id: int) -> dict:
        return self.facts(MOVE, move_id)

    def inv_button(self, s, move_id: int, activity: str, name: str, done, wizard=None) -> bool:
        return self.button(s, activity, MOVE, move_id, name, done, wizard=wizard)

    def create_invoice(self, role: str, expect_refusal: bool = False) -> int | None:
        """Order form > Create Invoice > dialog. Returns the new invoice id."""
        pl = self.plan
        s = self.s(role)
        s.open_form(SO, self.root_id)
        before = set(self.so()["invoice_ids"])
        new = lambda: set(self.so()["invoice_ids"]) - before  # noqa: E731
        up = lambda: s.page.locator(".modal button[name=create_invoices]").is_visible()  # noqa: E731
        prepare = lambda: self.so_button(s, PREPARE_INVOICE, "text:Create Invoice", up)  # noqa: E731
        prepare()
        s.idle(400)
        if pl["invoice_dialog_discard"] and not before and not expect_refusal:
            self.discard(s, DISCARD_INVOICE, SO, self.root_id, "invoice")
            prepare()
            s.idle(400)
        ok = self.so_button(s, CREATE_INVOICE, "create_invoices", lambda: bool(new()), wizard="invoice")
        if not ok:
            # Odoo refused; the dialog is still open
            self.discard(s, DISCARD_INVOICE, SO, self.root_id, "invoice")
            return None
        move_id = new().pop()
        s.wait_for(lambda: not s.modal_open(), what="invoice dialog to close")
        s.idle()
        self.n_invoices = getattr(self, "n_invoices", 0) + 1
        return move_id

    def invoicing(self):
        """One customer invoice for whatever is invoiceable now."""
        pl = self.plan
        if self.so()["invoice_status"] != "to invoice":
            return
        move_id = self.create_invoice(pl["invoice_by"])
        yield
        if move_id is None:
            return
        first = self.n_invoices == 1
        a = self.s("accountant")
        a.open_form(MOVE, move_id)
        if pl["cancel_invoice"] and first:
            # created with a mistake: cancel the draft, invoice again
            self.inv_button(a, move_id, CANCEL_INVOICE, "button_cancel",
                            lambda: self.inv(move_id)["state"] == "cancel")
            yield
            move_id = self.create_invoice("accountant")
            yield
            if move_id is None:
                return
            a.open_form(MOVE, move_id)
        if pl["set_invoice_date"] and first:
            def fill_date():
                inp = a.page.locator(".o_field_widget[name=invoice_date] input").first
                inp.click()
                inp.fill(dt.date.today().strftime("%m/%d/%Y"))
                inp.press("Enter")
                a.idle(150)
            self.event(a, SET_INVOICE_DATE, SAVE, MOVE, move_id, pre=fill_date,
                       post=lambda: self.settle(a, lambda: bool(self.inv(move_id)["invoice_date"])))
            if pl["split_invoice_session"]:
                yield
                a.open_form(MOVE, move_id)
        posted = lambda: self.inv(move_id)["state"] == "posted"  # noqa: E731
        confirm = lambda: self.inv_button(a, move_id, CONFIRM_INVOICE, "action_post", posted)  # noqa: E731
        confirm()
        if pl["reset_invoice"] and first:
            self.inv_button(a, move_id, RESET_INVOICE, "button_draft",
                            lambda: self.inv(move_id)["state"] == "draft")
            confirm()
        self.posted_invoice = move_id
        yield
        if pl["skip_payment"]:
            return
        yield from self.pay("accountant", move_id, PAY_LABELS,
                            discard_first=pl["payment_discard"] and first)

    # -- return and credit note ----------------------------------------------
    def returns(self):
        pl = self.plan
        done = self.admin.search(PICKING, [("id", "in", self.so()["picking_ids"]), ("state", "=", "done"),
                                           ("picking_type_code", "=", "outgoing")], order="id")
        move_id = getattr(self, "posted_invoice", None)
        if not done or not move_id:
            return
        w = self.s("warehouse")
        w.open_form(PICKING, done[0])
        before = set(self.so()["picking_ids"])
        new = lambda: set(self.so()["picking_ids"]) - before  # noqa: E731
        up = lambda: w.page.locator(".modal button[name=create_returns]").is_visible()  # noqa: E731
        prepare = lambda: self.button(w, PREPARE_RETURN, PICKING, done[0], "text:Return", up)  # noqa: E731
        prepare()
        w.idle(400)
        if pl["return_discard"]:
            self.discard(w, DISCARD_RETURN, PICKING, done[0], "return")
            prepare()
            w.idle(400)
        self.button(w, CREATE_RETURN, PICKING, done[0], "create_returns", lambda: bool(new()),
                    wizard="return")
        ret_id = new().pop()
        yield
        w.open_form(PICKING, ret_id)
        self.button(w, VALIDATE_RETURN, PICKING, ret_id, "button_validate",
                    lambda: self.facts(PICKING, ret_id)["state"] == "done")
        yield
        a = self.s("accountant")
        a.open_form(MOVE, move_id)
        inv_before = set(self.so()["invoice_ids"])
        new_cn = lambda: set(self.so()["invoice_ids"]) - inv_before  # noqa: E731
        up_cn = lambda: a.page.locator(".modal button[name=refund_moves]").is_visible()  # noqa: E731
        prep_cn = lambda: self.inv_button(a, move_id, PREPARE_CREDIT_NOTE, "action_reverse", up_cn)  # noqa: E731
        prep_cn()
        a.idle(400)
        if pl["credit_discard"]:
            self.discard(a, DISCARD_CREDIT_NOTE, MOVE, move_id, "credit")
            prep_cn()
            a.idle(400)
        self.inv_button(a, move_id, CREATE_CREDIT_NOTE, "refund_moves", lambda: bool(new_cn()),
                        wizard="credit")
        cn = new_cn().pop()
        a.wait_for(lambda: not a.modal_open(), what="credit note dialog to close")
        a.idle()
        self.inv_button(a, cn, CONFIRM_CREDIT_NOTE, "action_post", lambda: self.inv(cn)["state"] == "posted")
        yield
        if pl["refund"] and self.inv(cn)["payment_state"] in ("not_paid", "partial"):
            yield from self.pay("accountant", cn, REFUND_LABELS)

    # -- orchestration -------------------------------------------------------
    def run(self):
        pl = self.plan
        yield from self.create_quotation()
        if not (yield from self.quotation()):
            return
        if not (yield from self.after_confirmation()):
            return
        if pl["kind"] == "service":
            yield from self.invoicing()
        elif pl["kind"] == "order":
            # invoiced on ordered quantities: delivery and invoicing are independent
            if pl["invoice_before_delivery"]:
                yield from self.interleave(self.deliveries(pl["delivery_mode"]), self.invoicing())
            else:
                yield from self.deliveries(pl["delivery_mode"])
                yield from self.invoicing()
        else:
            # invoiced on delivered quantities: nothing to invoice before a delivery
            if pl["premature_invoice"]:
                self.create_invoice(pl["invoice_by"], expect_refusal=True)
                yield
            first = self.open_transfers("outgoing")
            if first and pl["delivery_cancelled"]:
                # the customer withdraws before shipping: delivery, then order cancelled
                w = self.s("warehouse")
                w.open_form(PICKING, first[0])
                self.button(w, CANCEL_DELIVERY, PICKING, first[0], "action_cancel",
                            lambda: self.facts(PICKING, first[0])["state"] == "cancel", confirm=True)
                yield
                m = self.s("sales_manager")
                m.open_form(SO, self.root_id)
                self.cancellation(m)
                yield
                return
            if first:
                yield from self.deliver(first[0], pl["delivery_mode"], True)
            if self.open_transfers("outgoing") and pl["split_invoicing"]:
                yield from self.interleave(self.deliveries("full"), self.invoicing())
            else:
                yield from self.deliveries("full")
            yield from self.invoicing()
        if pl["return"] and pl["kind"] != "service":
            yield from self.returns()
