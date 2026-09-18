# Evaluation

Tests the introduction claims of the paper against related-work baselines over
big, varied synthetic logs with a known hidden context, and with recorded case
attributes so the trace-clustering baselines can also cluster on context.

## Run

```bash
python evaluation/run_evaluation.py --quick     # ~3 min (used by tests)
python evaluation/run_evaluation.py --full      # default; translucent conformance is ON, uncapped
python evaluation/run_evaluation.py --full --no-translucent   # skip translucent fitness / precision
```

The enabled-set-aware **translucent fitness** and **translucent precision** are
reported by default (no size cap). Pass `--no-translucent` to skip them.

Outputs (`--out` / `--figdir` override the locations):

| path | content |
|---|---|
| `results/e1_separation.csv` | per log × seed × method: #groups, ARI / NMI / V-measure / purity vs. hidden context, enabled-signature incoherence |
| `results/e2_quality.csv` | per log × **every** grouping method (global, kappa, kappa_identifier, classical/translucent variants, and each clustering / attribute family at k=GT and k=silhouette): n_cases, #models, models-to-coverage, and (case-frequency-weighted over the method's groups) fitness / precision / f1 / generalisation / simplicity + translucent fitness / precision / f1 |
| `results/e3_sweeps.csv` | κ vs. best clustering, ARI across enabled-set noise and log size |
| `results/e4_taskmining.csv` | helpdesk case study: κ views × role confusion, ARI |
| `results/e5_case_study.csv` | ServiceDesk scenario (§5.4): per seed × noise × every grouping method — n_groups/n_models, ARI/NMI/V-measure/purity, and the 8 model-quality metrics |
| `results/case_study_table.tex` | **Table 4** of the section: ARI / translucent F1 for all 20 groupings at noise p ∈ {0, .05, .1, .15, .2}, best cell per column in `\textbf{}` (`precision` column dropped — todo T7). `findings*.tex` are legacy auto-bullet lists, no longer used |
| `figures/servicedesk_dejure.pdf` + `servicedesk_global.pdf` + `servicedesk_kappa_{agent,senior,specialist,supervisor}.pdf` | the six subfigures of the case-study figure — (a) the hand-built **de-jure** union workflow with the four diverging regions boxed and annotated per role, (b) one IMtf model of the whole ServiceDesk log, (c–f) the four per-view models κ induces. Regenerate (b)–(f) with `python figures/make_servicedesk_petrinets.py` (`font_size=18`); (a) plus editable `figures/servicedesk_*.drawio` copies of all six nets with `python figures/make_servicedesk_drawio.py`. Both standalone; both need the Graphviz `dot` binary. Supersedes the old hand-drawn `servicedesk_workflow.pdf` |
| `results/logs_overview_table.tex` | **Table 1**: the nine kept logs (`KEEP_LOGS` in `run_evaluation.py`), italic group header per family, `\|` rule before the κ-views result column |
| `results/summary_partition_table.tex` | **Table 2** (recovery): ARI / NMI / purity / enabl. sig. for all 20 groupings (`_PAPER_ROWS`), filtered to the nine kept logs, best cell per column in `\textbf{}` (`#groups` column dropped — todo T4) |
| `results/summary_quality_table.tex` | **Table 3** (model quality): #mdl / fit. / prec. / F1 / gen. / simp. / tr. fit. / tr. prec. / tr. F1 for all 20 groupings, nine kept logs, best cell per column in `\textbf{}` (`#mdl` and `fit.` excepted) — `_BEST` / `_bold_best` in `run_evaluation.py` |
| `results/summary_quality_caseweighted_table.tex` | case-weighted variant of Table 3 (standalone appendix only) |
| `results/attributes_table.tex` | still generated; **no longer used** — the section states role/clean/noisy NMI in one sentence |
| `figures/fig_scenario*.{pdf,png}` | `fig_scenario` (10-panel metric-vs-noise grid) kept **only for the standalone appendix**; `fig_perlog` / `fig_quality` / `fig_separation` / `fig_*` still render but are unused by the section |
| `results/{summary.csv,findings.tex}` | still generated, unused by the section |

## Modules

* `tpv/log/synth.py` — parameterised generators (`running_example_log` — the
  6-trace `L_run` of `tpv/log/demo.py` at scale, `k_view_log`,
  `partial_parallel_log`, `enterprise_log`, …) each returning
  `(log, ground_truth, attrs)`; `make_attributes` / `ATTRIBUTE_SCHEMA`;
  `LOG_SPECS` / `build_all(quick, seed)` yielding `(name, log, gt, attrs)`.
* `evaluation/methods.py` — the grouping methods (`group_kappa`,
  `group_classical_variants`, `group_translucent_variants`, control-flow /
  context-aware / trace2vec / enabled-only clustering, and
  `group_attribute_clustering` on the recorded clean / noisy / all attributes).
* `evaluation/metrics_eval.py` — `recovery`, `attribute_informativeness`,
  `enabled_incoherence`, `weighted_model_quality` (with `translucent=True`),
  `models_to_coverage`.
* `evaluation/plots.py` — the matplotlib figures.

## Paper integration

The evaluation section follows the house style of the authors' prior papers: a
numbered roadmap sentence and the subsections *Experimental Setup /
Recovering Hidden Context / Model Quality / Case Study: Sensitivity to Noise*,
no RQ labels, no separate "Threats to Validity" subsection (limitations are a
closing paragraph). It is **~4.5 pages, 1 figure + 4 tables** over the nine
`KEEP_LOGS`; every named baseline and metric is in the tables. Result numbers are
written into the prose; the header comment in each `.tex` lists which
`results/*.tex` file every table and number came from.

The tables are filtered views of the CSVs the harness produces for all 12 logs
and ~21 groupings — `KEEP_LOGS`, `LOG_DISPLAY`, `LOG_GROUP` (log table) and
`_PAPER_ROWS`, `PAPER_LABEL` (result-table rows) in `run_evaluation.py` select and
rename them; `_QUALITY_COLS` sets the model-quality columns. `fig_perlog`,
`fig_quality`, `fig_scenario`, `attributes_table.tex` still render/generate but are
unused by the section (`fig_scenario` is kept for the standalone appendix only).

* **`../paper_eval/05_eval.tex`** — drop-in for the paper's `sections/05_eval.tex`.
  Table 1 inline; Tables 2-4 `\input{tables/*}` (a `tables/` folder ships with it).
  `\cite{DBLP:...}` keys already in the paper's `mybib.bib`. See
  `../paper_eval/README.md`.
* **`evaluation/evaluation.tex`** — the same section as a `\section` fragment
  that `\input`s the four `evaluation/results/*` tables and `\includegraphics`
  the one Petri-net figure from `evaluation/figures/`. Paper preamble:
  `\usepackage{amsmath,amssymb,graphicx,booktabs,subcaption}` and
  `\graphicspath{{evaluation/}{evaluation/figures/}}`.
* **`evaluation/evaluation_standalone.tex`** — self-contained report with its own
  bibliography and a one-page appendix (`fig_scenario` + the case-weighted
  quality table). `pdflatex` twice.
