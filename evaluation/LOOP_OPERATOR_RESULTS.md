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
