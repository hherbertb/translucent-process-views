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
