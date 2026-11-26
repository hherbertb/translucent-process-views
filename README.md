# Translucent Process Views

In this repository, we provide the code for discovering *hidden process views* from translucent
event logs, together with the evaluation of our method. A translucent event log records, for every
event, the activities that were *enabled* at that moment, not only the one that was executed. Our
method groups traces by an abstraction function over those enabled activities, so no distance
function, no cluster count, and no clustering algorithm is needed.

We assume enabled activities are provided with the attribute/column name `enabled_activities`
(a separated list per event), as in our earlier work.

## Installation

    python -m venv venv
    venv\Scripts\activate          # Linux/macOS: source venv/bin/activate
    pip install -r requirements.txt

Python 3.13 is what we used. Rendering process models additionally requires the Graphviz `dot`
binary on the `PATH`.

To check the installation without any data, run the running example of the paper:

    from tpv.log.demo import running_example
    from tpv.views.views import induce_views

    for v in induce_views(running_example()):
        print(v.label, v.identifier.canonical_str(), v.sublog.n_cases)

which prints the three process views of Section 4.5:

    C1 seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h)) 2
    C2 seq(o, xor(b, c), xor(d, e), f, xor(g, h)) 2
    C3 seq(o, b, d, f, xor(g, h)) 2

## Discover Process Views from a Translucent Event Log

    from tpv.log.io import load_csv
    from tpv.views.views import induce_views

    log = load_csv("running-example.csv")
    views = induce_views(log)

    for v in views:
        print(v.label, v.identifier.canonical_str(), v.sublog.n_cases)

Each view is an equivalence class of translucent traces: all traces whose abstraction identifier
(Definition 4.10) is equal. The identifier is an expression over `seq`, `xor` and `and`, so
`seq(o, and(xor(b, c), xor(d, e)), f, xor(g, h))` reads as "`o`, then a choice between `b` and `c`
in parallel with a choice between `d` and `e`, then `f`, then either `g` or `h`".

`load_xes` and `from_dataframe` are available as well; see `tpv/log/io.py`.

## Discover One Process Model per View

    from tpv.discovery.api import discover_petri_net

    for v in induce_views(log):
        net, im, fm = discover_petri_net(v.sublog, variant="IMtf")

The `variant` parameter accepts the translucent Inductive Miner variants of our BPM 2024 work
(`IM`, `IMto`, `IMtf`, `IMts`). `tpv.discovery.api.view_petri_net` builds the model directly from a
view's identifier instead of mining it.

## Supported Views (Noisy Enabled Activities)

When enabled activities are read from screenshots, a single mis-read activity gives a trace an
identifier of its own. Supported views (Definition 4.13) keep the views that carry at least a share
`theta` of the cases and fold the remaining traces into the supported view whose availability
profile they match best.

    from evaluation.methods import group_kappa_supported

    grouping = group_kappa_supported(log, theta=0.01)   # trace -> view label

On noise-free logs nothing is folded and the result equals `induce_views`.

## Loops

The identifiers of Definition 4.1 have no loop operator, so repetition is unrolled: a trace that
runs a rework loop twice and the same trace running it five times get different identifiers. The
`loop` extension folds a repeated block back into `loop(...)` -- the process tree `*(K, tau)`,
"K one or more times":

    from tpv.views.abstraction import kappa
    from tpv.views.views import induce_views

    induce_views(log, loops="enabled")      # 2 views on the rework-loop log, any loop bound
    induce_views(log, loops="strict")       # 3 views
    induce_views(log)                       # 1..7 views, growing with the loop bound

`strict` folds a block pattern that was *executed* at least twice. `enabled` also folds a pattern
executed once whose activities are still in the local choice set of the following position -- the
enabled activities show that the loop *could* have continued -- which is what makes the view count
independent of how often the loop ran. Folding is off by default, so `kappa(sigma)` remains
Definition 4.10 exactly. See `evaluation/LOOP_OPERATOR_RESULTS.md`.

## Reproducing the Evaluation

All runners pin `PYTHONHASHSEED=0` on start (`evaluation/_repro.py`): pm4py's inductive miner and
several feature constructions iterate over sets of strings, so without a fixed hash seed the same
command produces different models on different runs.

### Synthetic logs (Tables 1--3)

    venv\Scripts\python evaluation\run_evaluation.py --full --seeds 3 \
        --paper-out "paper_final\ICPM_2026__Translucent_Variants(4)\tables"

Writes `evaluation/results/e1_separation.csv` (recovery), `e2_quality.csv` (model quality),
`e5_case_study.csv` (noise sweep) and the LaTeX tables. Budget a few hours; each experiment
checkpoints its CSV as soon as it finishes. `--tables-only` rebuilds the tables from existing CSVs
without recomputing, and `evaluation/run_case_study.py` reruns the noise sweep alone.

### Real-life logs (Table 4)

    venv\Scripts\python evaluation\run_semireal.py --xes-dir <folder with the XES logs>

Needs the **original** event logs, not the filtered translucent CSVs of our BPM 2024 artefact:

| log | attribute used as hidden context | source |
|---|---|---|
| Hospital Billing | `speciality` | 4TU, `10.4121/uuid:76c46b83-c930-4798-a1c9-4be94dfeb741` |
| Road Traffic Fine Management | `vehicleClass` | 4TU, `10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5` |

The script splits each log by the attribute, mines one IMf model per group (noise threshold 0.4),
enriches each group with *its own* model by replaying it, merges the sub-logs, drops the attribute,
and hands the result to every grouping method. It prints the retention rate per group and warns if
no classical variant occurs in more than one group, which would make the experiment vacuous.

`evaluation/scan_logs.py` screens further logs for a usable attribute (group balance,
directly-follows overlap between groups, and how many cases share a classical variant across
groups).

### Translucent logs from a real system (Odoo)

`simulation/` runs scripted agents in a local **Odoo 17 Community** through Playwright and records,
for every click, both what the screen offered and what the server would have accepted. It answers
the objection that replay-enriched logs assume the model whose views are then discovered: here the
enabled sets come from Odoo's own state machine and `res.groups`.

    cd simulation                                   # needs Docker Desktop
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m playwright install chromium
    .venv\Scripts\python -m sim.fetch_addons
    docker compose up -d
    .venv\Scripts\python -m sim.bootstrap
    .venv\Scripts\python -m sim.run --scenario p2p_shared --cases 40 --seed 31 --out output/run1

Two scenarios exist for the role-overlap experiment, and they are a pair:

| scenario | overlap | expected |
|---|---|---|
| `p2p_shared` | **group-gated**: at *to approve*, `purchase.group_purchase_manager` offers the manager `Approve Order` and the buyer not, while both may `Change Order` / `Cancel Order` | the enabled sets separate the roles |
| `o2c_shared` | **convention**: the sales roles have identical rights on every document of that process and differ only in who acts | nothing can separate them; `kappa` must score at the blind baseline |

Two scripts evaluate such a log. Run the first *before* generating at scale:

    venv\Scripts\python evaluation\check_overlap.py    <events.csv> --unit segment
    venv\Scripts\python evaluation\compare_channels.py <events.csv> --unit segment

`check_overlap.py` asks whether the log can demonstrate the claim at all -- whether the same
executed behaviour occurs under more than one role -- and fails a log whose executed activities
already determine the role. `compare_channels.py` runs `kappa` over each enabled channel against a
baseline that sees only the executed activities, overall and restricted to the contested traces.
Results and the sample sizes they need: `evaluation/ODOO_OVERLAP_RESULTS.md`.

### Checking the results

    venv\Scripts\python evaluation\verify_results.py     "paper_final\ICPM_2026__Translucent_Variants(4)"
    venv\Scripts\python evaluation\verify_independent.py "paper_final\ICPM_2026__Translucent_Variants(4)"
    venv\Scripts\python evaluation\check_paper_numbers.py "paper_final\ICPM_2026__Translucent_Variants(4)"
    venv\Scripts\python evaluation\verify_rerun.py --logs running_example --seed 1

`verify_results.py` recomputes every table cell from the raw per-run CSVs without using the
aggregation code. `verify_independent.py` re-implements the abstraction function from Definitions
4.2--4.10 without importing `tpv.views` and compares it against the library on every log and seed.
`check_paper_numbers.py` fails if the paper quotes a number that no run defines.
`verify_rerun.py` re-executes experiments and compares them with the recorded CSVs.

    venv\Scripts\python -m pytest tests -q

## Repository Structure

| path | contents |
|---|---|
| `tpv/log` | translucent log types, readers, synthetic generators, model-based enrichment |
| `tpv/views` | abstraction identifiers, the abstraction function, induced process views |
| `tpv/discovery` | translucent Inductive Miner variants and view-to-model conversion |
| `tpv/quality` | fitness, precision and their translucent counterparts |
| `evaluation` | experiment runners, baselines, metrics, verification scripts, result CSVs |
| `app` | small Streamlit GUI for inspecting views |
| `simulation` | scripted agents working in a local Odoo 17, producing translucent logs from a real system |
