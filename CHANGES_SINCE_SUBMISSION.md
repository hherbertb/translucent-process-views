# State of the work vs. the ICPM submission

Reference point: the submitted PDF (`ICPM_2026__Translucent_Variants-14.pdf`) and
its sources, `paper_final/ICPM_2026__Translucent_Variants(6)/`.

**The paper sources are unchanged.** Everything below is method, data and
artefact. The last section lists the edits the paper needs so that it states
what the artefact now does.

---

## 1. Method: 𝒦 has a loop operator

*Answers Reviewer 2 ("no loop operator, so repetition is unrolled").*

| | submission | now |
|---|---|---|
| 𝒦 (Def. 4.1) | ε, a, `seq`, `xor`, `and` | + `loop(K)` — K one or more times, process tree `*(K, τ)` |
| κ | Def. 4.10 | unchanged by default; opt-in folding of repeated blocks |
| rework-loop log, views | 1 → 7, growing with the loop bound | 2, constant (`enabled`) / 3, constant (`strict`) |

Two folding modes, because they claim different things:

- **`strict`** folds a block pattern **executed** at least twice. Asserts nothing
  the trace does not show, so "body once" stays apart from "body twice or more".
- **`enabled`** also folds a pattern executed **once** whose activities are still
  in the local choice set of the following position — the enabled sets show the
  loop *could* have continued. This is the mode that answers the objection, and
  the repair comes from the translucent information itself, not from a syntactic
  rewrite.

The folded pattern is the run's **primitive period**, which is what makes the
identifier canonical (`B B B B` has periods 1 and 2; only the shortest agrees
with `B B B`).

Folding is **off by default**, so every number in the submitted paper remains
reproducible; tests assert both modes leave every identifier of the running
example untouched. Code: `tpv/views/identifier.py`, `tpv/views/abstraction.py`
(`fold_loops`), `tpv/views/views.py` (`induce_views(log, loops=...)`).
Write-up: `evaluation/LOOP_OPERATOR_RESULTS.md`.

**Scope, stated plainly.** Folding changes almost nothing on the Odoo logs
(33 → 32 views over 213 segments). Those logs fragment because the work really
is varied, not because a loop is unrolled: rework in Odoo is *cancel and
re-confirm*, which passes through different states and so yields different
blocks rather than a repeated one. The loop operator closes one named gap; it is
not a general cure for view count.

## 2. Data: translucent logs from a real system

*Answers all three reviewers on circularity ("logs built around κ") and
artificiality ("public logs enriched by replay").*

`simulation/` — scripted Playwright agents working in a local **Odoo 17
Community**. Every event carries what the screen offered
(`enabled_activities_gui`) and, independently, what the server would have
accepted (`enabled_activities_backend`, and a case-scoped union). Neither comes
from a model, so κ is not being shown a log built from its own assumptions.

### The problem the shipped scenarios had

Only 1 of 21 activities was ever performed by more than one role, so the executed
sequence already identified the role and the enabled sets had nothing to
contribute. κ **lost** to a baseline that sees only the executed activities
(0.665 vs. 0.679 ARI).

### Two new scenarios, deliberately a pair

| scenario | overlap | mechanism | expected |
|---|---|---|---|
| `p2p_shared` | **group-gated** | at *to approve*, `purchase.group_purchase_manager` offers the manager `Approve Order` and the buyer not, while both may `Change Order` / `Cancel Order` | enabled sets separate the roles |
| `o2c_shared` | **convention** | the sales roles have identical rights on every document of that process and differ only in who acts | nothing can separate them — κ must sit at the blind baseline |

The second is the negative control. Without it, a reader can reasonably suspect
the gain in the first is an artefact of a scenario written to produce it.

### Results, `p2p_shared`

Whole log (`shared_n40b`, 40 cases, 213 handoff segments, 5 roles):

| grouping | groups | ARI | NMI |
|---|---:|---:|---:|
| executed sequence (no enabled info) | 37 | 0.530 | 0.698 |
| κ / GUI (screen) | 33 | **0.585** | 0.733 |
| κ / backend, document scope | 37 | 0.542 | 0.715 |
| κ / backend, case scope | 41 | 0.495 | 0.669 |

Contested traces only (identical executed sequence, more than one role):

| run | contested | baseline | κ/GUI | κ/doc | κ/case |
|---|---:|---:|---:|---:|---:|
| n24 | 8 | −0.149 | 0.401 | 0.401 | −0.149 |
| n40, seed 23 | 24 | −0.038 | 0.628 | 0.599 | 0.074 |
| n40b, seed 31 | 16 | 0.200 | **0.640** | 0.605 | 0.214 |

Where the executed sequence cannot separate the roles, the enabled activities
do — in three independent runs.

### Results, `o2c_shared` — the negative control

Whole log (40 cases, 156 segments, 4 roles):

| grouping | groups | ARI |
|---|---:|---:|
| executed sequence (no enabled info) | 50 | 0.234 |
| κ / GUI (screen) | 51 | 0.233 |
| κ / backend, document scope | 51 | 0.233 |
| κ / backend, case scope | 58 | 0.131 |

Contested traces only, 16 of 156: κ/GUI **0.000**, κ/document **0.000**,
κ/case −0.068.

Exactly zero against **0.640** for the same statistic on `p2p_shared`. That is
the dissociation the evaluation was missing: the gain is a property of
rights-gated overlap, not of a scenario written to produce a gain.

### Three findings worth carrying into the paper

1. **Document scope is the right semantics for "enabled".** Case scope sits at
   or near the blind baseline in every run: unioning over a case's documents
   inflates every local choice set and erases the discriminator. Definition 3.1
   cannot currently express the distinction.
2. **The GUI error channel is two-sided.** Earlier runs showed only
   over-reporting (the screen offers what the server refuses). One run surfaced
   11 **backend-only** events — the "same button always missed" case Reviewer 3
   hypothesised. (Its cause was a confound of mine, now fixed: edit factors
   below 1 dropped orders under the 5000 double-validation threshold, after
   which `rules` grants `Approve Order` to any writer.)
3. **GUI and backend can disagree about a whole document, not just a button.**
   The Odoo server accepts a quantity correction from the warehouse on a
   confirmed sales order; the Odoo web client refuses to open that form for that
   user at all (the form reads `crm.team`, which `stock.group_stock_user` may
   not). A discriminator that exists only in the backend channel is invisible to
   any GUI recorder — which is what ruled out the one rights-based overlap
   order-to-cash had to offer.

## 3. Instrumentation

| script | question |
|---|---|
| `evaluation/check_overlap.py` | *Can this log demonstrate the claim at all?* Does the same executed behaviour occur under more than one value of the hidden context? Run **before** generating at scale. |
| `evaluation/compare_channels.py` | *Does the enabled information buy anything?* κ over each enabled channel against the executed-only baseline, overall and on contested traces. |

The gate is now a **count** of contested traces (PASS ≥ 100, THIN ≥ 30), not the
≥ 50 % fraction placeholder. The fraction is the wrong bar for a generated log —
in Odoo most steps are legitimately role-private, so it stays at 7–11 % however
the scenario is written — while the statistic that has to hold still, the ARI on
contested traces, moved from −0.149 to 0.200 between runs with 8 and 16 contested
traces.

Under that gate the 40-case run **FAILs**: big enough to see the effect, too
small to quote.

## 4. Artefact and repository

| | submission | now |
|---|---|---|
| Odoo simulation | untracked, in a throwaway Claude worktree outside any repository with a remote | committed here as `simulation/` |
| cited Odoo logs | — | `evaluation/odoo/{seed42_n40_c4,shared_n40b}/` |
| tests | 77 | 100 (+`tests/test_loops.py`) |
| README | no loops, no Odoo | both documented, with the scenario pair and the two gate scripts |

## 5. Known limitations of the new evidence

- **Sample size.** Contested traces are 7–11 % of the log, against the ≥ 99 % the
  paper reports for hospital billing and road traffic. `p2p_shared` cannot close
  that gap: most purchase steps are legitimately role-private and buyer/manager
  differ at exactly one state. The Odoo claim must be carried by the
  contested-only number — *where execution is ambiguous, the enabled activities
  resolve it* — not by a whole-log ARI.
- **The contested baseline is unstable** at these sizes (−0.149 / −0.038 / 0.200
  across three runs). The *gain* is the result; the absolute is noise.
- **Order-to-cash yields no rights-based overlap**, by construction rather than by
  choice. Ruled out, with the reason, so they are not retried:
  `sales` vs. `sales_manager` (identical rights on every document of the
  process), `warehouse` on the sales order (GUI refuses the screen),
  `stock.picking` in state *assigned* (all four roles identical),
  `account.move` (only the accountant has rights at all).
- **The ticket scenario cannot serve this experiment**: `tickets.rules()` derives
  the enabled set from `can_write` plus ticket state only, so any two internal
  roles who can write a ticket get identical sets. No group change fixes it.

## 6. What the paper still has to say

Nothing below is done. Mapped to the source files:

| where | edit |
|---|---|
| `sections/04_method.tex:22` (Def. 4.1) | add the case `if K ∈ 𝒦 then loop(K) ∈ 𝒦` |
| `sections/04_method.tex`, after Def. 4.10 | the folding definition (the one new definition), both modes, and why the primitive period |
| `sections/05_eval.tex:23` (Table 1 caption) | the rework-loop log is no longer the exception: say under which mode, and keep the unrolled column for comparison. Table source: `evaluation/results/loop_penalty_table.tex` |
| `sections/06_conclusion.tex:8` | "an extension covering loops is promising" becomes a result, not future work |
| §3 (Def. 3.1) | state the enablement scope: the enabled set is per document, not per case, and say why (the measurement in §2 above) |
| §5 | the Odoo experiment: the scenario pair, the contested-trace result, the negative control, and the honest sample-size caveat |
| §5 | "We use Claude Opus 5 to create the artificial data" — rewrite. Reviewer 3 read it as *the datasets are LLM-generated*. `tpv/log/synth.py` is deterministic Python with `PYTHONHASHSEED=0`; the model wrote code, it did not generate data. |
| §1 / §5 | the reviewers' demands that are already answered by data computed and then cut for space: the `activitygen` noise mode, `n_groups`, the p = 0.3/0.4 sweep, the θ sweep (`c1_coarsening_*.csv`), `p1_cost`, `p2_determinism` |

Page budget: the submission is at the 13-page limit, and §5 is already dense. The
loop definition plus the Odoo experiment do not fit without cutting. That is a
venue decision — BPMDS allows a different budget than ICPM — so it is left open.
