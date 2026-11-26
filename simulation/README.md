# Translucent event logs from simulated work in Odoo

Scripted agents work in a real, locally running **Odoo Community 17** and
every action they take is logged together with the set of activities that
were *enabled* at that moment. Three processes are simulated:

| scenario | `--scenario` | Odoo apps | one case is | case ids |
|---|---|---|---|---|
| purchase-to-pay | `purchase_to_pay` | Purchase, Inventory, Invoicing | one procurement, RFQ to vendor payment | `PR0001`... |
| order-to-cash | `order_to_cash` | Sales, Inventory, Invoicing | one customer order, quotation to customer payment (and return / credit note) | `SO0001`... |
| ticket handling | `tickets` | OCA *Helpdesk Management* (`helpdesk_mgmt`) | one support ticket, portal submission to close | `TK0001`... |
| all three interleaved | `mixed` | all | as above, scenario drawn per case | unique across scenarios |

Each event carries two independently derived enabled sets:

| column | what it is |
|---|---|
| `enabled_activities_gui` | what the screen offered: visible, clickable action buttons just before the click, mapped to activity labels. This is what a desktop / browser recorder could observe. |
| `enabled_activities_backend` | ground truth: what the Odoo server would accept from that user on that document, computed over Odoo's RPC API from document state and the user's access rights. |
| `enabled_activities` | **copy of the GUI set**, under the column name the existing translucent miners read (`", "`-separated). |

Reading of "the system must have an inspectable GUI": the Odoo web UI and
customer portal are the real ones, not mocks. A person can open them in a
browser, log in as any role, watch the agents in headed mode, and inspect the
DOM the agents click on.

## Setup

Needs Docker Desktop and Python 3.11+ (built with 3.13) on the host.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m sim.fetch_addons
docker compose up -d
```

- `sim.fetch_addons` downloads the OCA `helpdesk_mgmt` addon at a pinned
  commit into `addons/` (mounted read-only into the container). Run it
  **before** `docker compose up`, otherwise Odoo starts without the addon.
- `docker compose up -d` starts PostgreSQL 16.4, Odoo 17.0 with 6 worker
  processes, and nginx 1.27 in front of it (all pinned by image digest).
  nginx sends the web client's websocket to Odoo's evented port and
  everything else to the HTTP port, Odoo's standard layout for worker mode.
  The GUI is at <http://127.0.0.1:8069>, bound to localhost only (not the LAN).
  Worker mode lets parallel runs use several CPU cores; with Odoo's default
  single process, four parallel runs were no faster than one.
- Chromium (about 280 MB) goes to `%LOCALAPPDATA%\ms-playwright`.
- `requirements.txt` also installs `pm4py`, used only by the quality analysis.

## Run

```bash
.venv\Scripts\python -m sim.run --scenario purchase_to_pay --cases 40 --seed 42
.venv\Scripts\python -m sim.run --scenario mixed --cases 60 --seed 42 --concurrency 6
```

The first run creates and configures the database by itself (about two
minutes); `python -m sim.bootstrap` does the same on its own and
`python -m sim.bootstrap --reset` drops the database and starts clean.

| option | meaning |
|---|---|
| `--scenario` | `purchase_to_pay`, `order_to_cash`, `tickets` or `mixed` |
| `--cases N` | number of cases |
| `--seed S` | same seed gives the same log (see *Agents*) |
| `--concurrency K` | cases open at the same time (interleaving) |
| `--headed` | show the browser windows, one per role |
| `--slow-mo MS` | extra delay per browser operation, for watching |
| `--think-scale X` | multiplier on agent think time (mean 0.4 s per action; `0` = fastest) |
| `--out DIR` | output folder (default `output/<scenario>_seed<S>_n<N>_c<K>`) |

Output per run:

- `events.csv` the log (schema below)
- `events.xes` the same log as XES (`concept:name`, `time:timestamp`, `org:resource`, `org:role`, the enabled sets and the scenario as string attributes)
- `miner.csv` the minimal input of the translucent miners: `case, activity, timestamp, enabled_activities` (UTC timestamps)
- `variants.csv` one row per case with its activity sequence
- `summary.json` counts, agreement of the two enabled sets, invariant checks, caught exceptions
- `exceptions.json` every exception the run caught (see check c)
- `errors/` screenshots, only if a case had to be aborted

Quality analysis and full rounds:

```bash
.venv\Scripts\python -m sim.quality output/<run> --repro output/<same-seed run>
.venv\Scripts\python -m sim.round --seed 101
```

`sim.round` runs all three scenarios (40 cases each) and a mixed run (60
cases), each twice with the same seed, four runs in parallel, then the
quality analysis of each pair. Results go to `output/round_<seed>/`.

Speed: about 3 s per event per run with `--think-scale 0`; runs in parallel
scale with CPU cores (each run needs a Chromium with one context per role,
roughly 0.5 GB of host memory). A full round (`sim.round`, 8 runs, 4 at a time) took 70-90 minutes on an 8-core machine.

## Open and inspect the GUI

Open <http://127.0.0.1:8069/web> and log in:

| role | scenario | login | password | Odoo groups |
|---|---|---|---|---|
| requester | P2P | `requester` | `requester-sim` | Purchase / User |
| purchasing agent | P2P | `buyer` | `buyer-sim` | Purchase / User |
| approver | P2P | `manager` | `manager-sim` | Purchase / Administrator |
| warehouse | P2P, O2C | `warehouse` | `warehouse-sim` | Inventory / User |
| accountant | P2P, O2C | `accountant` | `accountant-sim` | Invoicing / Billing, Purchase / User, Sales / All documents |
| salesperson | O2C | `sales` | `sales-sim` | Sales / Own documents only |
| sales manager | O2C | `salesmanager` | `salesmanager-sim` | Sales / Administrator |
| customer (portal) | tickets | `reporter` | `reporter-sim` | Portal |
| first-level agent | tickets | `agent` | `agent-sim` | Helpdesk / User: Team tickets, team *First Level* |
| second-level specialist | tickets | `specialist` | `specialist-sim` | Helpdesk / User: Team tickets, team *Second Level* |
| team lead | tickets | `lead` | `lead-sim` | Helpdesk / Manager, both teams |
| administrator | - | `admin` | `admin` | everything |

These are test credentials for the throw-away local database, defined in
`sim/config.py`. The customer logs in at the same URL and lands in the
portal (`/my/tickets`).

- Finding a case: P2P writes the case id into the order's *Vendor Reference*,
  O2C into the *Customer Reference*, tickets into the ticket title. Search
  for e.g. `PR0007` in the list views.
- `browser_url` in the log opens the exact document an event happened on.
- `--headed --slow-mo 300 --think-scale 2 --cases 3 --concurrency 1` is a
  comfortable speed for watching. Each role has its own window.
- `dom_path` (CSS) and `element_xpath` can be pasted into the browser dev
  tools (`$$()` / `$x()`) while the document is in the same state.
- `python -m sim.viewer output/<run>` writes `output/<run>/cases.html`: one
  collapsible section per case with every event, its role, the document state
  before and after, and the GUI and backend enabled sets side by side
  (differences highlighted, executed activity underlined, filters for
  scenario, differing sets and rejected attempts). Its *open* links go to the
  document in Odoo, which then shows its current state, not the state at that
  event.
- `python -m sim.probe <role> "<url fragment>"` prints what the agents'
  snapshot sees on a screen (development helper).

## The scenarios

### Purchase-to-pay

Roles and the normal path:

1. **requester** creates the RFQ (vendor, products, quantities)
2. **buyer** optionally changes it, optionally e-mails it, confirms it
3. **manager** approves orders of 5,000 or more (Odoo's built-in *Purchase
   Order Approval*, two-step validation)
4. **buyer** optionally sends the confirmed order by e-mail
5. **warehouse** validates the receipt (goods only)
6. **accountant** creates the vendor bill, fills in the bill date, confirms it, registers the payment
7. optionally the **buyer** locks the order and the **manager** unlocks it again

Variation: no RFQ e-mail; buyer changes; manager rejects (= cancels), buyer
sets back to draft, reduces and confirms again; RFQ cancelled, order rejected
for good, order cancelled after confirmation; receipt cancelled (goods never
arrive) and order cancelled; partial receipts with and without backorder;
bill before / between / after receipts for products billed on ordered
quantities, two bills with a backorder; bill created by mistake and
cancelled; mistakes Odoo refuses (confirming a bill without a date, a bill
before anything was received, validating a receipt with all quantities 0);
typo in a received quantity; e-mail / backorder / payment dialogs opened and
discarded; bill reset to draft and confirmed again; payment left open.

### Order-to-cash

Roles: **salesperson** (own documents only), **sales manager**,
**warehouse**, **accountant**.

1. salesperson creates the quotation, optionally revises it, sends it
2. optionally the customer asks for changes: revise and send again
3. optionally the customer declines: the quotation is cancelled through
   Odoo's cancellation dialog, sometimes reopened (*Set to Quotation*) and
   revised
4. the order is confirmed: by the salesperson, or by the sales manager for
   amounts of 6,000 or more (organisational convention, see limits)
5. optionally an order confirmation e-mail, a change of the confirmed order
   by the sales manager, or cancellation of the confirmed order
6. warehouse delivers: full, partial with backorder, partial without
   backorder; a delivery may be cancelled (customer withdraws), then the
   order is cancelled
7. invoice: *Create Invoice* on the order opens Odoo's invoicing dialog;
   salesperson or accountant creates the draft, accountant optionally sets
   the date, confirms, registers the payment. Invoicing policy decides the
   ordering: products invoiced on ordered quantities can be invoiced before
   delivery, products invoiced on delivered quantities only after it;
   with a backorder the first invoice can come between two deliveries
8. optionally a return: warehouse creates and validates the return of the
   delivery, accountant creates and confirms a credit note from the invoice
   and pays the refund

Mistakes Odoo refuses: creating an invoice for delivery-based products before
anything was delivered ("nothing to invoice"), validating a delivery whose
quantities were wiped. Further variation: dialogs opened and discarded
(e-mail, cancellation, invoice, payment, return, credit note), invoice
cancelled and created again, invoice reset to draft, typo in a delivered
quantity, payment left open.

### Ticket handling

Odoo's own *Helpdesk* app is Enterprise-only and is not used. The scenario
uses the free OCA module **`helpdesk_mgmt` 17.0.1.11.1** (AGPL-3.0,
<https://github.com/OCA/helpdesk>, pinned to commit `27dfbf3f8a`). It was
chosen over modelling tickets as Project tasks because it is a real ticket
system: ticket numbers, teams, stages with *closed* semantics, record rules
per team, and a customer portal where tickets are submitted, answered and
closed. It installs cleanly from the pinned commit (`sim.fetch_addons`).

Configuration (`sim/bootstrap.py`): stages New, In Progress, Awaiting,
Escalated, Resolved, Done, Cancelled, Rejected (Done and Cancelled may be set
by the customer from the portal); teams *First Level* (agent, lead) and
*Second Level* (specialist, lead); categories Hardware, Software, Access,
Billing.

Roles: **customer** (portal user), **first-level agent**, **second-level
specialist**, **team lead**.

1. customer submits the ticket on the portal (`/new/ticket`)
2. triage: agent takes it (*Assign to Me*) or the lead assigns it
   (team + assignee); duplicates are rejected; the customer may withdraw
3. assignee starts work; optionally hands over to the lead
4. waiting for the customer (*Awaiting*), customer answers in the portal,
   work resumes; the lead cancels the ticket if the customer stays silent
5. escalation: assignee escalates, lead reassigns to the second level,
   specialist accepts and works on it (and may wait for the customer, too)
6. resolve; the customer confirms in the portal (Done), or answers that the
   problem is back (reopen loop), or stays silent and the lead closes it
7. mistake: assignee clicks *Done* instead of *Resolved* and corrects it

Stage changes are made by clicking the form's status bar, as a person would.
The activity of a stage change depends on where the ticket comes from (e.g.
*In Progress* is *Start Work* from New, *Resume Work* from Awaiting, *Accept
Escalation* from Escalated, *Reopen Ticket* from Resolved).

The customer opens the ticket through the tokenised link Odoo puts into its
notification mails (`/my/ticket/<id>?access_token=...`). Without the token,
Odoo refuses portal chatter posts on tickets ("Access Denied": posting needs
write access, which portal users do not have).

### What Odoo Community (and this setup) does not offer

- **No purchase requisition document.** The requester creates the draft RFQ;
  the buyer takes over. (OCA `purchase_request` would add one; not installed.)
- **Purchase approval is a single amount threshold** with one approver group.
- **A purchase rejection has no state of its own**: the manager cancels.
- **No sales approval** in Community. The sales-manager confirmation for
  large orders is a convention the agents follow, not something Odoo
  enforces; the backend set therefore allows the salesperson to confirm too.
- **No ticket-level rejections by the server.** `helpdesk_mgmt` has no guards
  on stage or assignee changes, so the ticket scenario has no rejected
  attempts.
- No outgoing mail server. *Send* runs Odoo's normal mail composer and
  changes document states; the mails are queued and never leave the container.

## Agents

Common base (`sim/core.py`), used by all scenarios:

- **`Scenario`** describes one process: activity vocabulary, how screen
  buttons, dialog buttons and editable fields map to activities, the
  backend rule table, which documents belong to a case, the named causes of
  GUI/backend differences, and which state fields Odoo tracks.
- **`BaseCase`** is one case. All its choices come from a private random
  stream seeded with `(seed, scenario, case index)`. `event()` is the only
  way an agent acts: take the screen snapshot, compute both enabled sets,
  click, wait for Odoo's answer (or its error dialog), log one row. Shared
  flows: mail composer, stock transfer with backorder question, payment
  dialog, discard of any dialog.
- **Scheduler** (`sim/run.py`): keeps `--concurrency` cases open and picks
  one with its own seeded stream to do its next work session (one role, a
  few clicks). Browser actions run one after another, so cases interleave
  but never race. In a mixed run the scenario of case *i* is drawn from a
  stream seeded with `(seed, i)`.
- **Sessions**: one logged-in browser context per role (`sim/browser.py`).
  Every visit to a document reloads it, so each role sees what other roles
  changed.

Same seed, same case count and same concurrency therefore give the same
activity sequence per case and the same global order of events (check d).
Timestamps and Odoo's document numbers differ between runs.

Scenario modules: `sim/p2p.py`, `sim/o2c.py`, `sim/tickets.py`, registered
in `sim/scenarios.py`.

## Log schema (`events.csv`)

One row per agent action, i.e. per click on a business action (navigation to
a document is not an event). Columns that mean the same as in the
task-mining recorder's `events.csv` use the recorder's names.

| column | content |
|---|---|
| `seq` | global order of events in the run |
| `timestamp` | wall-clock time of the click, ISO 8601 with UTC offset *(recorder)* |
| `case_id` | the case, unique across scenarios *(recorder)* |
| `scenario` | `purchase_to_pay`, `order_to_cash` or `tickets` |
| `activity` | activity label from the scenario's vocabulary |
| `event_type` | always `click` *(recorder)* |
| `outcome` | `ok`, or `rejected` if Odoo answered with an error |
| `error` | Odoo's error text for rejected actions |
| `role`, `user` | acting role and Odoo login |
| `doc_model`, `doc_id`, `doc_name` | Odoo document on screen |
| `doc_state`, `doc_state_after` | its state before and after the action (invoices/bills: `state/payment_state`; tickets: `stage/assignee`) |
| `case_state`, `case_state_after` | state of all documents of the case before / after the action, e.g. `po:12=purchase;receipt:31=done;bill:9=draft/not_paid` |
| `enabled_activities` | = `enabled_activities_gui` (see top) |
| `enabled_activities_gui` | screen-derived enabled set |
| `enabled_activities_backend` | ground-truth enabled set for the acting user on the document on screen |
| `enabled_activities_backend_case` | ground truth over *all* documents of the case and *all* roles of the scenario: everything that could happen next in this case, whoever does it |
| `sets_agree` | 1 if GUI set == backend set |
| `only_gui`, `only_backend` | the differences |
| `executed_in_gui`, `executed_in_backend` | 1 if the executed activity is in the respective set |
| `gui_other_actions` | captions of visible buttons outside the vocabulary (Print, chatter, smart buttons, ...) |
| `active_app`, `active_window_title` | `Odoo`, browser page title *(recorder)* |
| `browser_url` | URL at the time of the click *(recorder)* |
| `element_name`, `element_type`, `element_id`, `element_rect`, `element_source`, `x`, `y`, `dom_path`, `dom_html` | the clicked element, as in the recorder *(recorder)*; `element_source` is always `dom` |
| `element_xpath` | XPath of the clicked element |
| `seed` | run seed |

Not emitted: `open_apps`, `screenshot_file`, `key`, `dom`. Sets are written
as `", ".join(sorted(set))`; no label contains a comma.

### Activity vocabularies

Defined in the scenario modules (`VOCABULARY`). Activities in `NEVER_EXECUTED`
appear in enabled sets but are deliberately not performed by the agents.

| scenario | activities |
|---|---|
| purchase-to-pay (27) | Create RFQ, Change Order, Compose RFQ Email, Send RFQ, Compose PO Email, Send PO, Discard Email, Confirm Order, Approve Order, Cancel Order, Set Order to Draft, Lock Order, Unlock Order, Create Bill, Set Received Quantity, Validate Receipt, Cancel Receipt, Create Backorder, No Backorder, Discard Backorder, Complete Bill, Confirm Bill, Cancel Bill, Reset Bill to Draft, Register Payment, Create Payment, Discard Payment |
| order-to-cash (46) | Create Quotation, Revise Quotation, Change Sales Order, Compose Quotation Email, Send Quotation, Compose Order Email, Send Order Confirmation, Discard Sales Email, Confirm Sales Order, Cancel Quotation, Start Order Cancellation, Confirm Order Cancellation, Send Cancellation Email, Discard Order Cancellation, Set to Quotation, Prepare Invoice, Create Invoice, Discard Invoice Creation, Set Delivered Quantity, Validate Delivery, Cancel Delivery, Create Delivery Backorder, No Delivery Backorder, Discard Delivery Backorder, Prepare Return, Create Return, Discard Return, Set Returned Quantity, Validate Return, Cancel Return\*, Set Invoice Date, Confirm Invoice, Cancel Invoice, Reset Invoice to Draft, Register Customer Payment, Create Customer Payment, Discard Customer Payment, Prepare Credit Note, Create Credit Note, Discard Credit Note, Confirm Credit Note, Cancel Credit Note\*, Reset Credit Note to Draft\*, Register Refund, Create Refund Payment, Discard Refund Payment\* |
| tickets (19) | Submit Ticket, Reply to Ticket, Confirm Resolution, Withdraw Ticket, Create Ticket\*, Assign to Me, Assign Ticket, Reassign Ticket, Start Work, Resume Work, Accept Escalation, Reopen Ticket, Reset to New\*, Wait for Customer, Escalate Ticket, Resolve Ticket, Close Ticket, Cancel Ticket, Reject Ticket |

\* never executed by the agents. For edit activities (Change Order, Revise
Quotation, Set ... Quantity, Complete Bill, Set Invoice Date, Assign /
Reassign Ticket) the logged click is the form's Save button after the field
was changed. Dialog steps are two events: opening the dialog (e.g. *Prepare
Invoice*, *Register Payment*) and confirming or discarding it.

## How each enabled set is derived

Both sets are taken at the same moment: after the agent has opened the
screen and before it touches anything.

### GUI set (`sim/browser.py` `SNAPSHOT_JS`, `Scenario.gui`)

1. Collect all `button`, `a.btn`, `a[role=button]`, `a[role=menuitem]`
   elements that are rendered (non-zero box, not `display:none` /
   `visibility:hidden`) and not disabled. If a dialog is open, only the
   top-most dialog is searched, because it covers the form. On portal pages
   the page body is searched.
2. Map each to an activity by the model in the URL and the button's Odoo
   `name` attribute (e.g. `purchase.order` + `button_confirm` = Confirm
   Order), by caption where Odoo gives no name (*Create Invoice*, *Return*),
   by the target stage id of status-bar buttons (tickets), by the dialog
   kind for dialog buttons, and by page path and caption on portal pages.
   Buttons whose meaning depends on the document (RFQ vs. order e-mail,
   invoice vs. credit note, delivery vs. return) are resolved from the
   status-bar caption or page title.
3. Edit activities are enabled if the field widget is visible and not
   read-only.
4. Everything else goes to `gui_other_actions`.

Known blind spots:

- **Visible is not allowed.** Odoo shows buttons the server will refuse (the
  `only_gui` causes below).
- **Not visible but allowed.** Some views hide actions the server would
  still run (the `only_backend` causes below).
- **One screen, one user.** The set covers the document on screen and the
  buttons this user's groups show. That the warehouse could validate the
  receipt is invisible while the purchase order is open; compare
  `enabled_activities_backend_case`.
- **Cross-case actions.** *New* is on every list and form of the case's main
  document, so Create RFQ / Create Quotation / Create Ticket are in most GUI
  sets of internal users although they start another case. Filter them if
  unwanted.
- Viewport dependent: on narrow windows Odoo folds status-bar buttons into a
  menu. The agents use 1500 x 950, where nothing is folded.
- The mapping is by Odoo 17.0 button names and captions; other versions or
  customised views need the tables in the scenario modules adjusted.
- Keyboard shortcuts, the gear menu, list-view bulk actions and chatter
  actions are not considered.

### Backend set (`Backend` in `sim/core.py`, `rules()` per scenario)

1. **Access rights, asked as the acting user** over XML-RPC:
   `check_access_rights` per model and operation, `res.users.has_group`,
   `check_access_rule(write)` and a `search_count` on the document so that
   record rules apply (e.g. own sales documents only, helpdesk team rules).
2. **Document facts**, read with the admin user (states, invoice status,
   amounts, quantities, dates, lines, assignee, stage).
3. **Rule table** per scenario that turns rights + facts into activities,
   transcribed from the Odoo 17 server code (purchase, sale, stock, account)
   and from `helpdesk_mgmt` (models and portal controllers).

Known blind spots:

- The rule tables are **hand-written models of the server**: Odoo has no API
  that lists permitted actions. They are checked against the server on every
  event (check b) but only in situations the agents reach.
- Server methods **without any guard** (`button_draft`, `button_done`,
  `button_unlock` on purchase orders, `assign_to_me` on tickets) are limited
  to the source state of their intended transition. In that respect the
  backend set is the intended state machine, not the literal RPC surface.
- Only preconditions in the tables are checked (no lock dates, fiscal
  constraints, custom modules).
- *Discard* in a dialog is a pure client action and counts as enabled
  whenever the dialog is.
- Ticket stages: `helpdesk_mgmt` lets any user with write access move a
  ticket to any stage, so every other stage is enabled; the sets are
  correspondingly large.

### Named causes of GUI/backend differences

Every difference between the two sets must fall into one of these (check g).
They are properties of Odoo's views, not of the agents.

| scenario | cause | side | activity | explanation |
|---|---|---|---|---|
| P2P | bill-date-missing | only GUI | Confirm Bill | Confirm is shown on every draft bill; `action_post` refuses without a bill date |
| P2P | cancel-after-receipt-or-bill | only GUI | Cancel Order | Cancel is shown on every confirmed order; `button_cancel` refuses after a receipt or a posted bill |
| P2P | nothing-to-bill | only GUI | Create Bill | shown on every confirmed order; refused when nothing is invoiceable |
| P2P | unlock-manager-only-in-view | only backend | Unlock Order | button shown to Purchase Administrators only; `button_unlock` has no group check |
| P2P | empty-receipt | only GUI | Validate Receipt | shown on every open receipt; refused when all quantities are 0 |
| O2C | nothing-to-invoice | only GUI | Create Invoice | the invoicing dialog always offers it; refused when nothing is invoiceable |
| O2C | invoice-dialog-hidden-when-invoiced | only backend | Prepare Invoice | the order hides *Create Invoice* once fully invoiced; the dialog itself has no guard |
| O2C | empty-delivery / empty-return | only GUI | Validate Delivery / Return | shown on every open transfer; refused when all quantities are 0 |
| tickets | portal-close-hidden-once-closed | only backend | Confirm Resolution, Withdraw Ticket | the portal hides its close buttons once the ticket has a closed date; `/ticket/close` still accepts them |

### Guarantees

- `enabled_activities` contains the executed activity. The raw GUI set must
  already contain it (check a, never repaired in practice).
- An accepted action is in the backend set, a rejected one is not (check b).
  Rejected attempts are the events whose executed activity is in the GUI set
  but not in the backend set.

## Quality method (`python -m sim.quality`)

Writes `quality.md` / `quality.json` into the run folder and exits with 1 if
a hard check fails. Checks run per scenario and, for a mixed run, over the
whole log.

**Hard checks**

| | check | how |
|---|---|---|
| a | executed activity in the GUI set | raw GUI set of every event |
| b | backend set matches the outcome | accepted => in backend set; rejected => not |
| c | no aborts, no hidden errors | no aborted case; every exception the run caught is recorded in `exceptions.json` and only the server's "access denied" answers to access questions are allowed; every case requested is in the log; rejected events carry Odoo's error text |
| d | reproducible | the same-seed rerun has identical traces per case and an identical global order |
| e | well-formed | timestamps non-decreasing per case, no duplicate events, 19 required fields filled |
| f | the log agrees with Odoo | for every document of every case: the state changes Odoo tracked in the chatter (`mail.tracking.value`) and the state changes in the log match one to one and in order (several Odoo changes inside one event are composed); untracked parts (payment state) and every field's final value are compared with the database |
| g | differences explained | every `only_gui` / `only_backend` entry maps to a named cause |
| h | loads in tools | `events.csv`, `events.xes` and `miner.csv` load in pm4py with the expected case and event counts; the translucent inductive miner (`discover_petri_net`, `translucent_variant` IMts) runs on the log |

Two kinds of Odoo state changes leave no tracking value and are declared per
scenario (`UNTRACKED`), with the reason; check f accepts them only if the
tracked changes before and after line up:

- `sale.order` draft -> sent: Odoo writes it with `tracking_disable`
  (`sale/models/sale_order.py:1499`)
- `sale.order` cancel -> draft (*Set to Quotation*): no tracking value in
  Odoo 17 (observed)

**Soft measures** (judged good / weak / poor)

| measure | poor | weak |
|---|---|---|
| variants | most frequent variant > 50 % of cases, every case unique, or < 3 variants | > 35 % or > 90 % unique |
| activity coverage of the vocabulary (without never-executed) | < 60 % | < 85 % |
| events with more than one enabled activity | < 50 % | < 80 % |
| role distribution | a scenario role without events | a role under 3 % |
| translucent vs. plain inductive miner | - | identical process trees |
| enabled-set size distribution | reported only | |

About the miner (check h): the copy of `translucent_discovery` at the root of
this worktree does not import (`ImportError: cannot import name
'get_parallel_relationships_frequent'` in `tDFG.py`: the function is missing
from its `utils/translucent_activity_relationships.py`). This is independent
of the input. The quality script therefore tries that copy first, records
the failure, and runs the complete copy in
`C:\Users\beyel\Documents\Code\Translucent Activity Relationships\TranslucentActivityRelationships`
(same API). That copy needs the parameter `tDFG_fall_through`; the script
passes `False`. Neither copy was modified. `miner.csv` matches the miners'
expected input (`case, activity, timestamp, enabled_activities`), and
`events.csv` loads as well.

## Results

Final state: the stop condition is met. Two consecutive full rounds with
different seeds (606 and 707), on identical code (fingerprint of `sim/*.py`
`9fc4f480`, recorded before and after in `output/code_fingerprint_r6r7.txt`),
pass every hard check in every scenario and in the mixed run, and no soft
measure is judged poor. Each run in a round was executed twice with the same
seed; check d compares the two.

Columns a-h are the hard checks; "top variant" is the share of cases in the
most frequent variant; "GUI = backend" is the share of events whose two
enabled sets are identical. Full reports: `output/round_<seed>/<run>/quality.md`.

#### Round seed 606

| run | scope | cases | events | activities | variants | top variant | rejected | GUI = backend | a | b | c | d | e | f | g | h | soft (poor/weak) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| purchase_to_pay | purchase_to_pay | 40 | 426 | 27 | 33 | 12% | 3 | 83.3% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| order_to_cash | order_to_cash | 40 | 478 | 33 | 34 | 8% | 3 | 98.7% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak |
| tickets | tickets | 40 | 297 | 17 | 23 | 12% | 0 | 100.0% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| mixed | order_to_cash | 23 | 261 | 32 | 20 | 9% | 1 | 99.2% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak |
| mixed | purchase_to_pay | 21 | 218 | 22 | 16 | 19% | 0 | 83.0% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak |
| mixed | tickets | 16 | 107 | 16 | 10 | 25% | 0 | 100.0% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| mixed | all | 60 | 586 | 70 | 46 | 7% | 1 | 93.3% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak, roles=weak |

#### Round seed 707

| run | scope | cases | events | activities | variants | top variant | rejected | GUI = backend | a | b | c | d | e | f | g | h | soft (poor/weak) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| purchase_to_pay | purchase_to_pay | 40 | 390 | 26 | 28 | 15% | 5 | 80.8% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| order_to_cash | order_to_cash | 40 | 494 | 40 | 32 | 15% | 2 | 99.2% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| tickets | tickets | 40 | 306 | 17 | 28 | 12% | 0 | 100.0% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| mixed | order_to_cash | 20 | 245 | 28 | 17 | 15% | 0 | 100.0% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak |
| mixed | purchase_to_pay | 14 | 157 | 22 | 12 | 14% | 3 | 81.5% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak |
| mixed | tickets | 26 | 194 | 17 | 17 | 12% | 0 | 100.0% | pass | pass | pass | pass | pass | pass | pass | pass | - |
| mixed | all | 60 | 596 | 67 | 46 | 5% | 3 | 95.1% | pass | pass | pass | pass | pass | pass | pass | pass | activity_coverage=weak, roles=weak |

Further numbers from these two rounds:

| | P2P | O2C | tickets | mixed (all) |
|---|---|---|---|---|
| check f: Odoo-tracked state changes matched (606 / 707) | 227 / 204 | 177 / 169 (+30 / 38 declared untracked) | 232 / 236 | per scenario as left |
| activity coverage (606 / 707) | 100 % / 96 % | 80 % / 98 % | 100 % / 100 % | 82 % / 79 % |
| events with > 1 enabled activity | 90-91 % | 90-91 % | 87 % | 89-90 % |
| mean size of `enabled_activities` | 3.3 | 3.0-3.1 | 7.0 | 3.9-4.4 |
| IMts vs. plain inductive miner | differs | differs | differs | differs |

GUI/backend differences in these rounds, all with a named cause (check g):
P2P *bill-date-missing* 35-36 events, *cancel-after-receipt-or-bill* 26-29,
*nothing-to-bill* 10, *empty-receipt* 2; O2C *empty-delivery* 2-4,
*nothing-to-invoice* 2; tickets none (the portal cause occurred in earlier
rounds). Why P2P agrees less (81-83 %) than O2C (99 %) and tickets (100 %):
Odoo's purchase views show *Confirm* on every draft bill and *Cancel* /
*Create Bill* on every confirmed order whatever the state behind them, while
the sales and helpdesk views hide such buttons more consistently.

Soft judgements: variants, multi-enabled share, roles per scenario and
translucent-vs-plain are good in every scope. Activity coverage is weak
(78-82 %) for O2C in some runs and for scenario sub-logs of the mixed run:
O2C has 41 executable activities, many on rare branches (returns, credit
notes, discards), and a mixed run has only 14-26 cases per scenario. The
role distribution of the whole mixed log is weak because 11 roles share 60
cases (the P2P manager and the O2C sales manager stay under 3 %).

### How the rounds went

| round (seed) | result | found | changed afterwards |
|---|---|---|---|
| 101 (1st attempt) | stopped after 4 min | Odoo in single-process mode: 4 parallel runs no faster than 1; XML-RPC calls returning None made Odoo log a traceback each time | Odoo 6 workers behind nginx; JSON-RPC client; visibility checks batched per role and model; cheaper after-state |
| 101 | O2C, mixed: c FAIL | transfer *Cancel* asks "Are you sure?"; the agents never answered (aborts) | agent answers the confirmation within the same event; O2C rare branches more likely |
| 202 | P2P: c FAIL; mixed: O2C variants poor | a header tooltip stayed open after an error dialog and covered the quantity cell (aborts); O2C cases all unique (23/23) in the mixed run | pointer moved away before cell edits; O2C given a dominant main path |
| 303 | P2P: d FAIL | race: an Odoo error dialog's body renders after the dialog, so a refused *Validate Receipt* was once taken as accepted | wait for the backorder dialog's own button; re-check for a late error before reporting success; P2P noise reduced |
| 404 | all pass, nothing poor | - | - |
| 505 | all hard checks pass; mixed: P2P variants poor (20/20 unique) | P2P had too many equally likely main paths for ~20 cases | P2P given a dominant main path |
| 606, 707 | all pass, nothing poor | - | (final) |

Rounds 4 and 5 both passed every hard check, but round 5 had a poor soft
measure, so the pair did not count.

### Headed mode

Run once: `--scenario mixed --cases 3 --seed 7 --headed --slow-mo 150
--think-scale 1` opened one visible Chromium window per role (11) on the
desktop, completed 3 cases / 32 events in 3:40 min without abort, and its
log passes all hard checks except d (no rerun made). Output:
`output/headed/`.

### Activities executed for the first time in this phase

From the gaps of the first reference run: Compose PO Email, Send PO, Unlock
Order, Cancel Receipt (receipt cancelled, then order), Cancel Bill (draft bill
created by mistake) and a refused *Validate Receipt* with all quantities 0.
Still deliberately never executed are the ones marked \* in the vocabulary
table.

### Not verified

- The worktree copy of the translucent miner could not be used (it does not
  import, see *Quality method*); check h ran the complete copy of the same
  miner from the sibling repository.
- Check f relies on Odoo's chatter tracking. Two sales-order transitions
  leave no tracking value; they are verified only through the continuity of
  the tracked changes around them. Payment states are untracked and only
  their final values are compared.
- The backend rule tables are verified by outcome (check b) only in the
  situations the agents reached; branches never taken (e.g. Unlock by a
  non-manager) are not tested against the server.
- Discovered models were compared structurally (process trees), not by
  fitness / precision.
- Headed mode was run once (3 cases); everything else ran headless.

## Known limits

- The backend sets are models of the server checked by outcome, not a
  server-side oracle (see above).
- Activity coverage depends on probabilities; rare branches (returns, credit
  notes, cancelled deliveries) may not occur in every 40-case run.
- The ticket scenario has no server-side rejections (the module has no
  guards); its translucency comes from the large stage sets.
- Timing: think time is drawn but defaults to a short mean; timestamps
  reflect the simulator's speed, not human working hours.
- Runs on the same database accumulate documents; nothing in the agents
  depends on that, and check d confirms it.

## Files

```
docker-compose.yml   Odoo 17.0 (6 workers) + PostgreSQL 16.4 + nginx 1.27, pinned by digest; mounts ./addons
nginx.conf           proxy: websocket to Odoo's evented port, the rest to HTTP
requirements.txt     playwright, pm4py
addons/              OCA helpdesk_mgmt (fetched, pinned commit; not part of this project)
sim/config.py        URL, roles/users, master data, thresholds, ticket stages/teams
sim/fetch_addons.py  downloads helpdesk_mgmt at the pinned commit
sim/bootstrap.py     database, modules, settings, users, master data (repeatable)
sim/rpc.py           XML-RPC client
sim/browser.py       Playwright session per role, DOM snapshot, element description
sim/core.py          Scenario, Backend, BaseCase: shared agent machinery
sim/p2p.py           purchase-to-pay scenario
sim/o2c.py           order-to-cash scenario
sim/tickets.py       ticket-handling scenario
sim/scenarios.py     registry
sim/run.py           scheduler, CSV logger, CLI
sim/stats.py         summary, variants, XES and miner CSV export, run comparison
sim/quality.py       quality analysis (hard checks, soft measures)
sim/round.py         one full quality round (all scenarios + mixed, each twice)
sim/probe.py         development helper: what the snapshot sees on a screen
```

Stop / remove:

```bash
docker compose down        # stop, keep the database
docker compose down -v     # stop and delete the database volumes
```

## Licence notes

- **Odoo Community Edition**: LGPL-3.0. The `odoo:17.0` Docker Official Image
  contains the Community edition only; Enterprise is not used.
- **OCA `helpdesk_mgmt`**: **AGPL-3.0-or-later**. It is downloaded at setup
  into `addons/`, not shipped with or modified by this project. AGPL matters
  if you run a modified version as a network service for others; running it
  locally for simulation is unaffected.
- This project does not contain, modify or link Odoo code. It talks to a
  running Odoo over HTTP (browser) and XML-RPC. The backend rule tables are
  independent descriptions of Odoo's behaviour.
- PostgreSQL: PostgreSQL Licence. nginx: BSD-2-Clause. Playwright: Apache-2.0. Chromium: BSD-style
  licences. pm4py: GPL-3.0 (used only by the quality analysis). pandas:
  BSD-3-Clause.
- No paid service, no LLM and no external network access is needed at run
  time; image, browser and addon downloads at setup are the only downloads.
- All names, customers, vendors and amounts in the database are made up.
