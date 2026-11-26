"""Order-to-cash with overlapping roles: the **negative control**.

`p2p_shared` shows the enabled activities separating two roles that the
executed sequence cannot separate.  A sceptical reader should ask whether
that gain is a property of the method or an artefact of a scenario built to
produce it.  This scenario is the control: an overlap of the *other* kind,
where the method must and does fail.

Odoo distinguishes two reasons why two roles may both perform one activity:

* **group-gated** -- the roles hold different groups, so a document in one
  state offers them different actions.  `p2p_shared` uses the one in
  purchase-to-pay: `purchase.group_purchase_manager` gates `Approve Order`,
  so at *to approve* the manager is offered one action more than the buyer.
  The enabled sets differ, and `kappa` resolves the overlap.
* **convention** -- the roles hold the *same* rights and differ only in who
  does what by habit or by internal policy.  The enabled sets are identical,
  so no translucent method can resolve the overlap, and a method that
  appeared to would be fitting noise.

Order-to-cash has only the second kind, which is why it is used here.
Measured against the running Odoo (``sim.probe``, ``Backend.rules``), on a
confirmed sales order that is not locked:

    role            enabled set on sale.order, state "sale"
    sales           Change Sales Order, Compose Order Email,
    sales_manager   Create Quotation, Prepare Invoice,
    accountant      Start Order Cancellation
    ---------------------------------------------------------------
    warehouse       Change Sales Order, Compose Order Email

`sales_team.group_sale_manager` differs from `sales_team.group_sale_salesman`
in *record rules* -- whose documents are visible -- not in what may be done
to a document one can write at all.  So `sales` and `sales_manager` are
indistinguishable on every document of this process, in every state.

`warehouse` is the one role whose rights do differ: `stock.group_stock_user`
carries `sale.order` write but neither `sale.order` create, nor
`sale.advance.payment.inv` create, nor `sale.order.cancel` create.  That
split is **not usable**, and the reason is worth recording: the Odoo *server*
accepts a quantity correction from the warehouse on a confirmed order, but
the Odoo *web client* refuses to open the sales-order form for that user at
all ("Access Error"; the form reads `crm.team`, which `stock.group_stock_user`
may not).  A GUI recorder can therefore never observe the warehouse at that
screen, so the discriminator exists in the backend channel and not in the one
the method is meant to consume.  (`Create Bill` in `p2p_shared` was ruled out
the same way, there by the server rather than by the client.)

What this scenario therefore does: it draws the actor of the two activities
that occur under more than one role -- `Confirm Sales Order`, inherited from
`o2c.Case.owner`, and `Change Sales Order` -- from two roles with identical
rights.  The expected result is that `kappa` scores at the blind baseline on
the contested traces.  Anything above that would indicate a leak.
"""
from __future__ import annotations

from . import o2c
from .o2c import (CHANGE_SALES_ORDER, COMPOSE_ORDER_EMAIL, DISCARD_SALES_EMAIL, SO,
                  SEND_ORDER_CONFIRMATION, OrderToCash)

# identical rights on every document of this process; see the module docstring
CHANGE_ACTORS = ("sales", "sales_manager")


class OrderToCashShared(OrderToCash):
    name = "o2c_shared"
    prefix = "OS"


SCENARIO = OrderToCashShared()


class Case(o2c.Case):
    sc = SCENARIO

    def draw_plan(self) -> dict:
        pl = super().draw_plan()
        r = self.rng
        # the plain scenario changes a confirmed order in 5 % of cases, which
        # is too rare to measure anything
        pl["change_after_confirm"] = True
        pl["change_actors"] = [r.choice(CHANGE_ACTORS)
                               for _ in range(r.choices([1, 2], [0.6, 0.4])[0])]
        return pl

    def owner(self) -> str:
        """Who confirms.  The plain scenario ties this to the order amount,
        which makes the role a function of the document and lets a grouping
        recover it from the amount rather than from the behaviour.  Here it is
        drawn, so that the two roles are genuinely interchangeable."""
        return self.rng.choice(CHANGE_ACTORS)

    def after_confirmation(self):
        """As `o2c.Case.after_confirmation`, but the corrections on the
        confirmed order are performed by a drawn role of identical rights
        instead of always by the manager."""
        pl = self.plan
        if pl["send_confirmation"]:
            s = self.s("sales")
            s.open_form(SO, self.root_id)
            self.mail_dialog(s, SO, self.root_id, "action_quotation_send", COMPOSE_ORDER_EMAIL,
                             SEND_ORDER_CONFIRMATION, DISCARD_SALES_EMAIL, False, lambda: True)
            yield
        for actor in pl["change_actors"]:
            s = self.s(actor)
            s.open_form(SO, self.root_id)
            self.change_lines(s, CHANGE_SALES_ORDER, self.rng.choice([1.2, 1.5, 2.0]))
            yield
        if pl["cancel_after_confirm"]:
            m = self.s("sales_manager")
            m.open_form(SO, self.root_id)
            self.cancellation(m)
            yield
            return False
        return True
