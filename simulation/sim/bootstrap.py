"""Repeatable bootstrap of the Odoo database used by the simulation.

Creates the database, installs the apps of the three scenarios
(purchase-to-pay, order-to-cash, ticket handling), configures them and
creates role users and master data. Safe to run again: existing records are
updated, not duplicated.

    python -m sim.bootstrap            # create if missing
    python -m sim.bootstrap --reset    # drop the database first
"""
from __future__ import annotations

import argparse
import time
import urllib.request

from . import config
from .fetch_addons import fetch
from .rpc import Odoo, db_service


def wait_for_odoo(timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            urllib.request.urlopen(f"{config.URL}/web/database/selector", timeout=5).read()
            return
        except Exception as exc:  # noqa: BLE001 - any failure means "not up yet"
            if time.time() > deadline:
                raise RuntimeError(
                    f"Odoo not reachable at {config.URL}. Run `docker compose up -d` first."
                ) from exc
            time.sleep(2)


def ensure_database(reset: bool = False) -> bool:
    """Return True if the database was created by this call."""
    db = db_service()
    if config.DB in db.list():
        if not reset:
            return False
        print(f"[bootstrap] dropping database {config.DB}")
        db.drop(config.MASTER_PASSWORD, config.DB)
    print(f"[bootstrap] creating database {config.DB} (takes a minute)")
    db.create_database(config.MASTER_PASSWORD, config.DB, False, "en_US",
                       config.ADMIN_PASSWORD, config.ADMIN_LOGIN, "US", "")
    return True


def install_modules(admin: Odoo) -> None:
    admin.call("ir.module.module", "update_list")
    known = admin.search_read("ir.module.module", [("name", "in", config.MODULES)], ["name", "state"])
    missing = set(config.MODULES) - {m["name"] for m in known}
    if missing:
        raise RuntimeError(
            f"Odoo does not see the addon(s) {sorted(missing)}. The folder ./addons must be "
            "mounted into the container: run `python -m sim.fetch_addons`, then "
            "`docker compose up -d` again (it recreates the container with the mount).")
    ids = [m["id"] for m in known if m["state"] != "installed"]
    if ids:
        print(f"[bootstrap] installing modules (takes a few minutes)")
        admin.call("ir.module.module", "button_immediate_install", ids)


def upsert(admin: Odoo, model: str, domain: list, vals: dict) -> int:
    ids = admin.search(model, domain, context={"active_test": False})
    if ids:
        admin.write(model, ids[:1], vals)
        return ids[0]
    return admin.create(model, vals)


def configure_users(admin: Odoo) -> dict[str, int]:
    uids = {}
    for role, spec in config.ROLES.items():
        group_ids = [admin.ref(x) for x in spec["groups"]]
        uids[role] = upsert(admin, "res.users", [("login", "=", spec["login"])], {
            "name": spec["name"],
            "login": spec["login"],
            "password": spec["password"],
            "email": f"{spec['login']}@simco.example.com",
            # in-app notifications only: no outgoing mail server is configured
            "notification_type": "inbox" if not spec.get("portal") else "email",
            "groups_id": [(6, 0, group_ids)],
        })
    print(f"[bootstrap] {len(uids)} users: {', '.join(s['login'] for s in config.ROLES.values())}")
    return uids


def configure_purchase(admin: Odoo) -> None:
    company_id = admin.search("res.company", [])[0]
    admin.write("res.company", [company_id], {
        "name": "Simco Manufacturing",
        "po_double_validation": "two_step",
        "po_double_validation_amount": config.APPROVAL_THRESHOLD,
        "po_lock": "edit",
    })
    for v in config.VENDORS:
        upsert(admin, "res.partner", [("name", "=", v["name"])], {
            "name": v["name"], "email": v["email"], "city": v["city"],
            "is_company": True, "supplier_rank": 1,
        })
    for p in config.PRODUCTS:
        upsert(admin, "product.template", [("name", "=", p["name"])], {
            "name": p["name"],
            "detailed_type": "product" if p["kind"] == "goods" else "service",
            "purchase_method": p["policy"],
            "standard_price": p["price"],
            "list_price": round(p["price"] * 1.3, 2),
            "purchase_ok": True,
            "sale_ok": False,
            "supplier_taxes_id": [(6, 0, [])],  # no taxes: amounts stay easy to read
        })
    print(f"[bootstrap] purchase: {len(config.VENDORS)} vendors, {len(config.PRODUCTS)} products, "
          f"approval threshold {config.APPROVAL_THRESHOLD:.0f}")


def configure_sales(admin: Odoo) -> None:
    for c in config.CUSTOMERS:
        upsert(admin, "res.partner", [("name", "=", c["name"])], {
            "name": c["name"], "email": c["email"], "city": c["city"],
            "is_company": True, "customer_rank": 1,
        })
    stock_loc = admin.search_read("stock.warehouse", [], ["lot_stock_id"], limit=1)[0]["lot_stock_id"][0]
    for p in config.SALE_PRODUCTS:
        tmpl = upsert(admin, "product.template", [("name", "=", p["name"])], {
            "name": p["name"],
            "detailed_type": "product" if p["kind"] == "goods" else "service",
            "invoice_policy": p["policy"],
            "list_price": p["price"],
            "standard_price": round(p["price"] * 0.6, 2),
            "sale_ok": True,
            "purchase_ok": False,
            "taxes_id": [(6, 0, [])],
        })
        if p["kind"] != "goods":
            continue
        prod = admin.search_read("product.product", [("product_tmpl_id", "=", tmpl)],
                                 ["qty_available"])[0]
        if prod["qty_available"] < config.SALE_STOCK_ON_HAND / 2:
            q = admin.call("stock.quant", "create", {
                "product_id": prod["id"], "location_id": stock_loc,
                "inventory_quantity": config.SALE_STOCK_ON_HAND}, context={"inventory_mode": True})
            admin.call_void("stock.quant", "action_apply_inventory", [q])
    print(f"[bootstrap] sales: {len(config.CUSTOMERS)} customers, {len(config.SALE_PRODUCTS)} products")


def configure_tickets(admin: Odoo, uids: dict[str, int]) -> None:
    for seq, st in enumerate(config.TICKET_STAGES, start=1):
        vals = {"name": st["name"], "sequence": seq, "closed": st["closed"], "fold": False,
                "unattended": st["name"] == "New", "close_from_portal": bool(st.get("portal")),
                "mail_template_id": False}
        if st["xmlid"]:
            admin.write("helpdesk.ticket.stage", [admin.ref(f"helpdesk_mgmt.{st['xmlid']}")], vals)
        else:
            upsert(admin, "helpdesk.ticket.stage", [("name", "=", st["name"])], vals)
    for team, roles in config.TICKET_TEAMS.items():
        upsert(admin, "helpdesk.ticket.team", [("name", "=", team)], {
            "name": team, "user_ids": [(6, 0, [uids[r] for r in roles])]})
    for cat in config.TICKET_CATEGORIES:
        upsert(admin, "helpdesk.ticket.category", [("name", "=", cat)], {"name": cat})
    print(f"[bootstrap] tickets: {len(config.TICKET_STAGES)} stages, {len(config.TICKET_TEAMS)} teams")


def bootstrap(reset: bool = False) -> None:
    fetch()
    wait_for_odoo()
    ensure_database(reset)
    admin = Odoo(config.ADMIN_LOGIN, config.ADMIN_PASSWORD)
    install_modules(admin)
    uids = configure_users(admin)
    configure_purchase(admin)
    configure_sales(admin)
    configure_tickets(admin, uids)
    print(f"[bootstrap] done. GUI: {config.URL}/web  (admin / admin, or any role login)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="drop and recreate the database")
    args = ap.parse_args()
    bootstrap(reset=args.reset)


if __name__ == "__main__":
    main()
