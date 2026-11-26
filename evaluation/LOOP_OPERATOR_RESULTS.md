# The loop operator — what it fixes and what it does not

Reviewer 2 of the ICPM submission: the abstraction identifiers of Definition 4.1
have no loop operator, so repetition is unrolled and a trace that runs a rework
loop twice is a different view from the same trace running it five times.
Property experiment P3 had already quantified this: on the synthetic rework-loop
log the view count equals the number of distinct trace lengths, exactly.

## What was added

`loop(K_1)` ∈ 𝒦 for every K_1 ∈ 𝒦 — K_1 executed **one or more** times, the
process tree `*(K_1, τ)` (`tpv/views/identifier.py`).

A folding step over the interval sequence of Definition 4.8
(`tpv.views.abstraction.fold_loops`), in two readings:

| mode | folds | claims |
|---|---|---|
| `strict` | a block pattern **executed** ≥ 2 times | nothing the trace does not show |
| `enabled` | also a pattern executed **once** whose activities are still in the local choice set (Def. 4.3) of the following position | the enabled sets reveal the option to repeat |

The pattern folded is the run's **primitive period**. That is what makes the
identifier canonical: `B B B B` has periods 1 and 2, and only the shortest gives
the same identifier as `B B B`.

Folding is **off by default**: `kappa(sigma)` is Definition 4.10 unchanged, so
every number already reported stays reproducible. `tests/test_loops.py` asserts
that both modes leave every identifier of the running example untouched.

## Result on the log the limitation was stated for

`loop_process_log(600, seed=13)`, body = `request_docs, assess`:

| max. rework | κ views | κ_loop strict | κ_loop enabled | distinct lengths |
|---:|---:|---:|---:|---:|
| 0 | 1 | 1 | 1 | 1 |
| 1 | 2 | 2 | 2 | 2 |
| 2 | 3 | 3 | **2** | 3 |
| 3 | 4 | **3** | **2** | 4 |
| 4 | 5 | 3 | 2 | 5 |
| 5 | 6 | 3 | 2 | 6 |
| 6 | 7 | 3 | 2 | 7 |
| 8 | 7 | 3 | 2 | 7 |
| 10 | 7 | 3 | 2 | 7 |

Both folded columns are constant from the bound at which they can first fold.
The identifiers under `enabled`:

```
seq(register, and(decide, xor(assess, request_docs)), archive)                    # loop not taken
seq(register, loop(and(assess, request_docs)),
              and(decide, xor(assess, request_docs)), archive)                    # loop taken
```

Two views, whatever the loop bound: *loop taken* and *loop not taken*. That is
the answer to the objection.

Note what carries it. After a single execution of the body, the enabled sets
still offer `assess` and `request_docs` — the local choice set of the next
position is `{assess, request_docs}` — so the log shows that the loop *could*
have continued. `strict` cannot use that and needs two executions, which is why
it stops at three views. The repair of the loop limitation therefore comes from
the translucent information itself, not from a syntactic rewrite.

## What folding costs in model quality

One model per view, built from the view's identifier, metrics case-frequency
weighted over the views (`view_model_quality(mode="identifier")`):

| max. rework | mode | #models | fitness | precision | generalisation | simplicity |
|---:|---|---:|---:|---:|---:|---:|
| 2 | κ | 3 | 1.000 | 0.667 | 0.750 | 0.835 |
| 2 | strict | 3 | 1.000 | 0.650 | 0.698 | 0.833 |
| 2 | enabled | **2** | 1.000 | 0.658 | 0.733 | 0.827 |
| 4 | κ | 5 | 1.000 | 0.667 | 0.747 | 0.834 |
| 4 | strict | 3 | 1.000 | 0.649 | 0.751 | 0.833 |
| 4 | enabled | **2** | 1.000 | 0.655 | 0.733 | 0.827 |
| 6 | κ | 7 | 1.000 | 0.667 | 0.701 | 0.834 |
| 6 | strict | 3 | 1.000 | 0.649 | 0.752 | 0.833 |
| 6 | enabled | **2** | 1.000 | 0.655 | 0.733 | 0.827 |
| 10 | κ | 7 | 1.000 | 0.667 | 0.722 | 0.834 |
| 10 | strict | 3 | 1.000 | 0.649 | 0.698 | 0.833 |
| 10 | enabled | **2** | 1.000 | 0.655 | 0.640 | 0.827 |

**Fitness stays exactly 1.000**: the folded model accepts every iteration count,
which is what folding is for. The price is about 0.012 precision — the model
allows repetition the traces in that view did not all take — for 7 models down
to 2.

Per view at `max_rework = 4` the trade is sharper than the weighted average
suggests: κ's five unrolled views each score precision 0.667 but their
generalisation decays with the iteration count (0.759, 0.689, 0.554, 0.437,
0.254 — the long traces are each supported by a handful of cases), while the
single folded view scores 0.636 precision at 0.427 generalisation. Folding moves
the cost from "many models each fitted to one length" to "one model that admits
a length it did not see".

## Where it does not help: the Odoo logs

Views induced over handoff segments, GUI channel:

| log | unit | traces | κ | strict | enabled |
|---|---|---:|---:|---:|---:|
| `seed42_n40_c4` (shipped p2p) | case | 40 | 32 | 32 | 32 |
| `seed42_n40_c4` | segment | 180 | 21 | 21 | 21 |
| `shared_n40b` (p2p overlap) | case | 40 | 29 | 29 | 29 |
| `shared_n40b` | segment | 213 | 33 | 33 | **32** |

Folding changes almost nothing. The Odoo logs fragment because the work really
is varied, not because a loop is unrolled: rework there is a *cancel and
re-confirm* of one document, which passes through different states and so
produces different blocks rather than a repeated one. Under `enabled`, 72 of
213 segments do receive a `loop(...)` identifier — the option to repeat is
common — but the folding relabels them without merging them.

So the loop operator is worth having and must not be sold as a fix for view
count in general. It bounds one specific failure, the one the reviewer named.

## Reproducing

```bash
venv\Scripts\python -m pytest tests/test_loops.py -q
venv\Scripts\python evaluation\run_properties.py       # rewrites p3_loop.csv, loop_penalty_table.tex
```
