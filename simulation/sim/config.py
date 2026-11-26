"""Static configuration: connection, roles and master data.

Everything here is test data for a throw-away local Odoo instance.
"""
from __future__ import annotations

import os

URL = os.environ.get("SIM_ODOO_URL", "http://127.0.0.1:8069")
DB = os.environ.get("SIM_ODOO_DB", "odoo_sim")
MASTER_PASSWORD = os.environ.get("SIM_ODOO_MASTER", "admin")  # image default
ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin"

# purchase-to-pay, order-to-cash, ticket handling (OCA helpdesk_mgmt, AGPL-3)
MODULES = ["purchase", "stock", "account", "purchase_stock",
           "sale_management", "sale_stock", "helpdesk_mgmt"]

# Purchase orders at or above this untaxed amount need a manager's approval
# (Odoo Community: Purchase > Settings > Purchase Order Approval).
APPROVAL_THRESHOLD = 5000.0
# Organisational convention only (Odoo Community has no sales approval):
# quotations at or above this amount are confirmed by the sales manager.
SALES_REVIEW_THRESHOLD = 6000.0

# role -> user. `groups` are XML ids of Odoo security groups.
# `portal` users are external (customer portal), all others internal.
ROLES = {
    # --- purchase-to-pay ---
    "requester": {
        "login": "requester", "password": "requester-sim", "name": "Rita Requester",
        "groups": ["base.group_user", "purchase.group_purchase_user"],
    },
    "buyer": {
        "login": "buyer", "password": "buyer-sim", "name": "Ben Buyer",
        "groups": ["base.group_user", "purchase.group_purchase_user"],
    },
    "manager": {
        "login": "manager", "password": "manager-sim", "name": "Mona Manager",
        "groups": ["base.group_user", "purchase.group_purchase_manager"],
    },
    # --- shared by purchase-to-pay and order-to-cash ---
    "warehouse": {
        "login": "warehouse", "password": "warehouse-sim", "name": "Walt Warehouse",
        "groups": ["base.group_user", "stock.group_stock_user"],
    },
    "accountant": {
        "login": "accountant", "password": "accountant-sim", "name": "Ada Accountant",
        "groups": ["base.group_user", "account.group_account_invoice",
                   "purchase.group_purchase_user", "sales_team.group_sale_salesman_all_leads"],
    },
    # --- order-to-cash ---
    "sales": {
        "login": "sales", "password": "sales-sim", "name": "Sam Sales",
        "groups": ["base.group_user", "sales_team.group_sale_salesman"],  # own documents only
    },
    "sales_manager": {
        "login": "salesmanager", "password": "salesmanager-sim", "name": "Selma Salesmanager",
        "groups": ["base.group_user", "sales_team.group_sale_manager"],
    },
    # --- ticket handling ---
    "reporter": {
        "login": "reporter", "password": "reporter-sim", "name": "Rob Reporter",
        "groups": ["base.group_portal"], "portal": True,
    },
    "agent": {
        "login": "agent", "password": "agent-sim", "name": "Anna Agent",
        "groups": ["base.group_user", "helpdesk_mgmt.group_helpdesk_user_team"],
    },
    "specialist": {
        "login": "specialist", "password": "specialist-sim", "name": "Spiro Specialist",
        "groups": ["base.group_user", "helpdesk_mgmt.group_helpdesk_user_team"],
    },
    "lead": {
        "login": "lead", "password": "lead-sim", "name": "Lea Lead",
        "groups": ["base.group_user", "helpdesk_mgmt.group_helpdesk_manager"],
    },
}

VENDORS = [
    {"name": "Nordwind Office Supply", "email": "sales@nordwind.example.com", "city": "Hamburg"},
    {"name": "Kessler Industrial Parts", "email": "orders@kessler.example.com", "city": "Stuttgart"},
    {"name": "Lumen IT Hardware", "email": "b2b@lumen.example.com", "city": "Munich"},
    {"name": "Brandt Facility Services", "email": "service@brandt.example.com", "city": "Cologne"},
    {"name": "Aurora Packaging", "email": "kontakt@aurora.example.com", "city": "Leipzig"},
]

# kind: goods -> storable, receipt needed; service -> no receipt.
# policy: Odoo "control policy": receive = bill received quantities (bill only
# after receipt), purchase = bill ordered quantities (bill may precede receipt).
PRODUCTS = [
    {"name": "Office Chair", "kind": "goods", "policy": "receive", "price": 180.0},
    {"name": "Laptop 14 inch", "kind": "goods", "policy": "purchase", "price": 1150.0},
    {"name": "Monitor 27 inch", "kind": "goods", "policy": "receive", "price": 320.0},
    {"name": "Steel Bracket", "kind": "goods", "policy": "receive", "price": 4.5},
    {"name": "Hydraulic Pump", "kind": "goods", "policy": "purchase", "price": 2400.0},
    {"name": "Cardboard Box L", "kind": "goods", "policy": "receive", "price": 1.2},
    {"name": "Printer Toner", "kind": "goods", "policy": "receive", "price": 65.0},
    {"name": "Cleaning Service (month)", "kind": "service", "policy": "purchase", "price": 900.0},
    {"name": "IT Consulting (day)", "kind": "service", "policy": "purchase", "price": 1300.0},
    {"name": "Machine Maintenance", "kind": "service", "policy": "purchase", "price": 650.0},
]

CUSTOMERS = [
    {"name": "Falkenberg Logistik", "email": "einkauf@falkenberg.example.com", "city": "Bremen"},
    {"name": "Meridian Retail Group", "email": "procurement@meridian.example.com", "city": "Frankfurt"},
    {"name": "Tannhaus Engineering", "email": "office@tannhaus.example.com", "city": "Dresden"},
    {"name": "Solvik Health Clinics", "email": "supply@solvik.example.com", "city": "Kiel"},
    {"name": "Ostwind Hotels", "email": "purchasing@ostwind.example.com", "city": "Rostock"},
]

# policy: Odoo "invoicing policy": delivery = invoice delivered quantities
# (invoice only after delivery), order = invoice ordered quantities
# (invoice may precede delivery).
SALE_PRODUCTS = [
    {"name": "Standing Desk", "kind": "goods", "policy": "delivery", "price": 540.0},
    {"name": "Conference Table", "kind": "goods", "policy": "delivery", "price": 1250.0},
    {"name": "LED Panel Light", "kind": "goods", "policy": "delivery", "price": 48.0},
    {"name": "Filing Cabinet", "kind": "goods", "policy": "delivery", "price": 210.0},
    {"name": "Workstation Bundle", "kind": "goods", "policy": "order", "price": 1890.0},
    {"name": "Server Rack 42U", "kind": "goods", "policy": "order", "price": 2600.0},
    {"name": "Label Printer", "kind": "goods", "policy": "order", "price": 330.0},
    {"name": "Installation Service", "kind": "service", "policy": "order", "price": 750.0},
    {"name": "Training Day", "kind": "service", "policy": "order", "price": 1400.0},
    {"name": "Support Contract (year)", "kind": "service", "policy": "order", "price": 2900.0},
]
SALE_STOCK_ON_HAND = 1_000_000  # enough that deliveries never wait for stock

# Ticket stages, in status-bar order. The module's six default stages are
# kept (matched by XML id) and two are added. `portal` = the customer may
# move the ticket there from the portal page.
TICKET_STAGES = [
    {"name": "New", "xmlid": "helpdesk_ticket_stage_new", "closed": False},
    {"name": "In Progress", "xmlid": "helpdesk_ticket_stage_in_progress", "closed": False},
    {"name": "Awaiting", "xmlid": "helpdesk_ticket_stage_awaiting", "closed": False},
    {"name": "Escalated", "xmlid": None, "closed": False},
    {"name": "Resolved", "xmlid": None, "closed": False},
    {"name": "Done", "xmlid": "helpdesk_ticket_stage_done", "closed": True, "portal": True},
    {"name": "Cancelled", "xmlid": "helpdesk_ticket_stage_cancelled", "closed": True, "portal": True},
    {"name": "Rejected", "xmlid": "helpdesk_ticket_stage_rejected", "closed": True},
]
TICKET_TEAMS = {"First Level": ["agent", "lead"], "Second Level": ["specialist", "lead"]}
TICKET_CATEGORIES = ["Hardware", "Software", "Access", "Billing"]
