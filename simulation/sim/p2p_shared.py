"""Purchase-to-pay with overlapping roles.

The plain `purchase_to_pay` scenario gives every role its own private set of
activities, so the executed sequence already identifies the role and a
translucent log has nothing left to contribute.  This variant keeps the same
process and changes only *who acts*, at the one place where two roles can do
the same thing and still be told apart by what else was on offer:

    state "to approve", on the purchase order
        buyer    -> {Change Order, Cancel Order}
        manager  -> {Change Order, Cancel Order, Approve Order}

(`PurchaseToPay.rules`: APPROVE_ORDER is gated on
`purchase.group_purchase_manager`.)  Both roles may edit or cancel an order
awaiting approval, so `Change Order` and `Cancel Order` become shared
activities whose *enabled* set still separates buyer from manager.

Orders are drawn above the approval threshold so that every case passes
through "to approve".  Everything else -- documents, states, labels, the
backend rules -- is inherited unchanged, which keeps the two logs comparable.
"""
from __future__ import annotations

from . import config, p2p
from .p2p import PO, PurchaseToPay

# roles entitled to act on a purchase order awaiting approval
REVIEW_ACTORS = ("buyer", "manager")


class PurchaseToPayShared(PurchaseToPay):
    name = "p2p_shared"
    prefix = "PS"


SCENARIO = PurchaseToPayShared()


class Case(p2p.Case):
    sc = SCENARIO

    def draw_plan(self) -> dict:
        pl = super().draw_plan()
        r = self.rng
        # Every case should reach "to approve", which is the only state where
        # the buyer's and the manager's enabled sets differ.
        pl["lines"] = [dict(ln, qty=max(ln["qty"], self._qty_for_threshold(ln)))
                       for ln in pl["lines"]]
        pl["manager_rejects"] = r.random() < 0.25
        pl["rework_after_reject"] = True
        # one or two edits while the order waits for approval, each by a role
        # drawn from those entitled to make it
        pl["review_tweaks"] = [r.choice(REVIEW_ACTORS)
                               for _ in range(r.choices([1, 2, 3], [0.4, 0.4, 0.2])[0])]
        pl["reject_actor"] = "manager"          # only a manager can approve/reject
        pl["cancel_actor"] = r.choice(REVIEW_ACTORS)
        return pl

    @staticmethod
    def _qty_for_threshold(line: dict) -> int:
        """Quantity that puts a single line over the double-validation amount."""
        price = next((p["price"] for p in config.PRODUCTS if p["name"] == line["product"]), None)
        if not price:
            return line["qty"]
        return int(config.APPROVAL_THRESHOLD // price) + 2

    def approval(self):
        """As in `p2p.Case.approval`, but the edits and the cancellation while
        the order awaits approval are performed by a drawn entitled role.

        Edit factors are all > 1: `rules` grants APPROVE_ORDER to any writer
        once `amount_total` drops below the double-validation amount, which
        would make buyer and manager indistinguishable on exactly the traces
        this scenario exists to contest."""
        rejected_once = False
        tweaks = list(self.plan["review_tweaks"])
        while self.po()["state"] == "to approve":
            # --- shared activity: Change Order, by buyer or manager ----------
            if tweaks:
                actor = tweaks.pop(0)
                s = self.s(actor)
                s.open_form(PO, self.root_id)
                self.change_order(s, self.rng.choice([1.2, 1.5, 1.8]))
                yield
                continue
            m = self.s(self.plan["reject_actor"])
            m.open_form(PO, self.root_id)
            if self.plan["manager_rejects"] and not rejected_once:
                rejected_once = True
                # --- shared activity: Cancel Order, by buyer or manager ------
                c = self.s(self.plan["cancel_actor"])
                c.open_form(PO, self.root_id)
                self.po_button(c, p2p.CANCEL_ORDER, "button_cancel", self.state_is("cancel"))
                yield
                b = self.s("buyer")
                b.open_form(PO, self.root_id)
                self.po_button(b, p2p.SET_ORDER_TO_DRAFT, "button_draft", self.state_is("draft"))
                self.change_order(b, self.rng.choice([1.2, 1.4, 1.6]))
                self.po_button(b, p2p.CONFIRM_ORDER, "button_confirm",
                               self.state_is("to approve", "purchase"))
                yield
            else:
                self.po_button(m, p2p.APPROVE_ORDER, "button_approve", self.state_is("purchase"))
                yield
        return self.po()["state"] == "purchase"
