# Odoo role-overlap experiment — results

Why: all three ICPM reviewers attacked the evaluation as circular (synthetic logs
built around κ) or artificial (public logs enriched by replay). The Odoo
simulation answers both — enabled sets come from Odoo's own state machine and
`res.groups` access rights — but the shipped scenarios gave every role a private
set of activities, so the executed sequence already identified the role and the
enabled activities had nothing to contribute.

`sim/p2p_shared.py` changes **only who acts**, at the one state where two roles
can do the same thing and still be told apart.

## The mechanism

`PurchaseToPay.rules` gates `Approve Order` on `purchase.group_purchase_manager`.
At state *to approve* on a purchase order:

| role | enabled set |
|---|---|
| buyer | `Cancel Order, Change Order` |
| manager | `Cancel Order, Change Order, `**`Approve Order`** |

So `Change Order` / `Cancel Order` performed there are the same executed activity
under two roles, separated only by what else was on offer. Orders are drawn above
the 5000 approval threshold so every case reaches that state.

Two placements were ruled out by the rules, not by preference:

- `Create Bill` needs `MOVE` create rights, which the buyer lacks — the server
  would refuse it.
- At *draft*/*sent* buyer and manager are **identical**; overlapping there would
  create shared activities with no discriminator and actively hurt.

## Results

Traces are handoff segments: maximal runs of consecutive events by one role.
Ground truth is the role; it is dropped before grouping.

### Whole log (`shared_n40b`, 40 cases, 213 segments)

| grouping | groups | ARI | NMI |
|---|---:|---:|---:|
| executed sequence (no enabled info) | 37 | 0.530 | 0.698 |
| κ / GUI (screen) | 33 | **0.585** | 0.733 |
| κ / backend, document scope | 37 | 0.542 | 0.715 |
| κ / backend, case scope | 41 | 0.495 | 0.669 |

### Contested traces only — identical executed sequence, >1 role

| run | contested | baseline | κ/GUI | κ/doc | κ/case |
|---|---:|---:|---:|---:|---:|
| n24 (truncated) | 8 | −0.149 | 0.401 | 0.401 | −0.149 |
| n40, seed 23 | 24 | −0.038 | 0.628 | 0.599 | 0.074 |
| n40b, seed 31 | 16 | 0.200 | **0.640** | 0.605 | 0.214 |

Where the executed sequence cannot separate the roles, the enabled activities do.

### Before the intervention, for comparison

On the shipped `purchase_to_pay` log κ **lost** to the blind baseline:

| grouping | ARI |
|---|---:|
| executed sequence | 0.679 |
| κ / GUI | 0.695 |
| κ / backend, document | 0.665 |
| κ / backend, case | 0.608 |

## Findings

1. **Document scope is the right semantics for "enabled".** Case scope sits at or
   near the blind baseline in every run. Unioning over the case's documents
   inflates every local choice set and erases the discriminator. This agrees with
   the screenshot motivation, so the empirical and the conceptual argument point
   the same way.
2. **Tickets cannot serve this experiment.** `tickets.rules()` derives the enabled
   set from `can_write` plus ticket state only, so any two internal roles who can
   write a ticket get identical sets. Agent/specialist/lead are indistinguishable
   by construction; no group change fixes it.
3. **GUI noise is two-sided.** Earlier runs showed only over-reporting (screen
   offers what the server refuses). Seed 23 surfaced 11 **backend-only** events —
   server allows, screen does not show — all buyer, all at *to approve*. Cause:
   `rules` grants `Approve Order` to any writer once `amount_total` drops below
   the double-validation amount, and edit factors below 1 shrank orders under it.
   Fixed by requiring factors > 1; the anomaly disappears.

## Limitation to state in the paper

Contested traces are 7–11 % of the log, against the ≥99 % the paper reports for
hospital billing and road traffic. p2p cannot close that gap: most purchase steps
are legitimately role-private and buyer/manager differ at exactly one state. The
Odoo claim should therefore be carried by the contested-only number — *where
execution is ambiguous, enabled activities resolve it* — not by a whole-log ARI.

## Reproducing

```bash
# in simulation/ , Docker running
.venv\Scripts\python -m sim.bootstrap
.venv\Scripts\python -m sim.run --scenario p2p_shared --cases 40 --seed 31 \
    --concurrency 6 --think-scale 0 --out output/shared_n40b
```

```bash
# in translucent_process_views/
venv\Scripts\python evaluation\check_overlap.py    <events.csv> --unit segment
venv\Scripts\python evaluation\compare_channels.py <events.csv> --unit segment
```

`check_overlap.py`'s ≥50 % threshold is a placeholder and should probably become a
minimum contested *count* instead.
