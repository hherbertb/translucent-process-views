"""Translucent Process Views -- interactive explorer.

Run with::

    streamlit run app/streamlit_app.py

Implements "Discovering Hidden Process Views from Translucent Event Logs"
(Beyel & van der Aalst, ICPM 2026): the abstraction function ``kappa`` groups
translucent traces into hidden process views, and each view gets its own model.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

# make the project importable when launched via `streamlit run`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

warnings.filterwarnings("ignore")
os.environ.setdefault("PM4PY_SHOW_PROGRESS_BAR", "False")

import pandas as pd
import streamlit as st

try:  # silence pm4py progress bars if the constant exists
    from pm4py.util import constants as _pm_constants

    _pm_constants.SHOW_PROGRESS_BAR = False
except Exception:  # pragma: no cover
    pass

from tpv.discovery.api import VARIANTS, discover_process_tree, view_process_tree
from tpv.log import io as tio
from tpv.log.demo import hidden_context_log, loop_process_log, running_example
from tpv.log.tasks import task_mining_helpdesk
from tpv.log.types import TranslucentLog, executed_projection, pi_act
from tpv.views.views import assign_view, induce_views, view_variant_crosstab
from tpv.viz.identifier_viz import identifier_svg
from tpv.viz.models import model_svg
from tpv.viz.variants import render_log

st.set_page_config(page_title="Translucent Process Views", layout="wide")

ACCENT = "#4C78A8"


# --------------------------------------------------------------------------- #
# cached compute
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _demo_running() -> TranslucentLog:
    return running_example()


@st.cache_data(show_spinner=False)
def _demo_hidden(a: int, c: int, u: int) -> TranslucentLog:
    log, _ = hidden_context_log({"admin": a, "clerk": c, "auditor": u})
    return log


@st.cache_data(show_spinner=False)
def _demo_helpdesk(na: int, ns: int, rework: bool) -> TranslucentLog:
    log, _ = task_mining_helpdesk(na, ns, rework=rework)
    return log


@st.cache_data(show_spinner=False)
def _demo_loop(n: int) -> TranslucentLog:
    return loop_process_log(n)


@st.cache_data(show_spinner=False)
def _load_upload(data: bytes, name: str, enabled_key: str, separator: str) -> TranslucentLog:
    suffix = Path(name).suffix.lower()
    tmp = Path(st.session_state["_tmpdir"]) / name
    tmp.write_bytes(data)
    if suffix in (".xes", ".gz"):
        return tio.load_xes(str(tmp), enabled_key=enabled_key, separator=separator)
    return tio.load_csv(
        str(tmp),
        enabled_key=enabled_key or None,
        separator=separator,
    )


@st.cache_data(show_spinner=True)
def _views(_log: TranslucentLog, key: str):
    return induce_views(_log)


@st.cache_data(show_spinner=True)
def _view_tree_svg(identifier_str: str, _tree, kind: str) -> str:
    return model_svg(_tree, kind)


@st.cache_data(show_spinner=True)
def _compare_frame(_log: TranslucentLog, key: str, mode: str, variant: str, nt: float, translucent: bool):
    from tpv.quality.metrics import global_vs_views

    return global_vs_views(_log, induce_views(_log), view_mode=mode,
                           global_variant=variant, noise_threshold=nt,
                           translucent=translucent)


# --------------------------------------------------------------------------- #
# sidebar
# --------------------------------------------------------------------------- #
if "_tmpdir" not in st.session_state:
    import tempfile

    st.session_state["_tmpdir"] = tempfile.mkdtemp(prefix="tpv-")

st.sidebar.title("Translucent Process Views")
source = st.sidebar.radio(
    "Event log",
    [
        "Running example (paper)",
        "Hidden-context demo",
        "Task-mining helpdesk",
        "Loop process",
        "Upload XES / CSV",
    ],
)

enabled_key = st.sidebar.text_input("Enabled-activities attribute", value="enabled_activities")
separator = st.sidebar.text_input("Enabled-activities separator", value=",")

log: TranslucentLog
if source == "Running example (paper)":
    log = _demo_running()
elif source == "Hidden-context demo":
    a = st.sidebar.slider("admin cases", 5, 100, 40, 5)
    c = st.sidebar.slider("clerk cases", 5, 100, 40, 5)
    u = st.sidebar.slider("auditor cases", 5, 100, 20, 5)
    log = _demo_hidden(a, c, u)
elif source == "Task-mining helpdesk":
    na = st.sidebar.slider("agent cases", 10, 200, 80, 10)
    ns = st.sidebar.slider("supervisor cases", 10, 200, 55, 5)
    rework = st.sidebar.toggle("agent rework loop", value=False)
    log = _demo_helpdesk(na, ns, rework)
    st.sidebar.caption("Full case study on the **Task mining** page (left nav).")
elif source == "Loop process":
    nc = st.sidebar.slider("cases", 40, 400, 120, 20)
    log = _demo_loop(nc)
    st.sidebar.caption("Single context, real rework loop (`assess ↔ request_docs`).")
else:
    up = st.sidebar.file_uploader("Log file", type=["xes", "csv", "gz"])
    if up is None:
        st.info("Upload an XES or CSV translucent log to continue.")
        st.stop()
    log = _load_upload(up.getvalue(), up.name, enabled_key, separator)

st.sidebar.divider()
view_mode = st.sidebar.selectbox(
    "Per-view model",
    ["identifier", "translucent_im", "classic_im"],
    help="'identifier' renders the view's abstraction identifier directly; the "
    "others mine the view's sub-log.",
)
miner_variant = st.sidebar.selectbox("Translucent IM variant", list(VARIANTS), index=3)
noise = st.sidebar.slider("Noise threshold (IMf)", 0.0, 0.9, 0.0, 0.05)
model_kind = st.sidebar.selectbox("Model diagram", ["petri", "tree", "bpmn"])

log_key = f"{source}|{getattr(log, 'name', '')}|{log.n_cases}|{log.n_events}"
views = _views(log, log_key)
assignment = assign_view(log, views)


# --------------------------------------------------------------------------- #
# header + KPIs
# --------------------------------------------------------------------------- #
st.title("Hidden process views from translucent event logs")
k = st.columns(6)
k[0].metric("Cases", log.n_cases)
k[1].metric("Events", log.n_events)
k[2].metric("Activities", len(log.activities))
k[3].metric("Classical variants", len(log.classical_variants()))
k[4].metric("Translucent variants", len(log.trace_set()))
k[5].metric("Process views", len(views))

tab_log, tab_views, tab_compare, tab_export = st.tabs(
    ["Log", "Views", "Global vs. views", "Export"]
)


# --------------------------------------------------------------------------- #
# Log tab
# --------------------------------------------------------------------------- #
with tab_log:
    st.subheader("Translucent variant explorer")
    st.caption(
        "Each row is a distinct translucent trace. The brackets show the "
        "parallel-supported intervals that make `and(...)` blocks."
    )
    labels = {t: f"{assignment[t]}" for t in log.trace_set()}
    html, vheight = render_log(log, accent=ACCENT, labels=labels)
    st.components.v1.html(html, height=vheight + 8, scrolling=True)

    st.subheader("Enabled-activity heatmap")
    universe = sorted(log.activities)
    rows = []
    for trace, count in log.variants.items():
        for pos, event in enumerate(trace, start=1):
            for a in event[1]:
                if a in universe:
                    rows.append({"position": pos, "activity": a, "cases": count})
    if rows:
        hm = (
            pd.DataFrame(rows)
            .groupby(["activity", "position"], as_index=False)["cases"]
            .sum()
        )
        try:
            import altair as alt

            chart = (
                alt.Chart(hm)
                .mark_rect()
                .encode(
                    x=alt.X("position:O", title="trace position"),
                    y=alt.Y("activity:O", title=None),
                    color=alt.Color("cases:Q", scale=alt.Scale(scheme="blues"), title="cases enabled"),
                    tooltip=["activity", "position", "cases"],
                )
                .properties(height=24 * len(universe) + 40)
            )
            st.altair_chart(chart, width="stretch")
        except Exception:
            st.dataframe(hm.pivot(index="activity", columns="position", values="cases").fillna(0))


# --------------------------------------------------------------------------- #
# Views tab
# --------------------------------------------------------------------------- #
with tab_views:
    left, right = st.columns([1, 2], gap="large")
    with left:
        st.subheader("Discovered views")
        for v in views:
            with st.container(border=True):
                st.markdown(
                    f"**{v.label}** &nbsp; `{v.frequency}` cases &nbsp; "
                    f"`{v.n_variants}` classical / `{v.n_translucent_traces}` translucent variants"
                )
                st.progress(v.coverage(log.n_cases))
                st.code(v.identifier.canonical_str(), language="text")
        pick = st.radio("Inspect view", [v.label for v in views], label_visibility="collapsed")

    selected = next(v for v in views if v.label == pick)
    with right:
        st.subheader(f"{selected.label} - abstraction identifier")
        st.image(identifier_svg(selected.identifier), width="stretch")

        st.subheader("Discovered model")
        tree = view_process_tree(
            selected, mode=view_mode, variant=miner_variant, noise_threshold=noise
        )
        try:
            svg = _view_tree_svg(f"{selected.key}|{view_mode}|{miner_variant}|{noise}", tree, model_kind)
            st.image(svg, width="stretch")
        except Exception as exc:  # pragma: no cover
            st.warning(f"Could not render {model_kind} model: {exc}")
            st.code(str(tree))

        st.subheader("Traces in this view")
        vhtml, vh = render_log(selected.sublog, accent=ACCENT)
        st.components.v1.html(vhtml, height=vh + 8, scrolling=True)

    st.divider()
    st.subheader("Classical variant x view")
    st.caption(
        "One classical variant can appear in several views; one view can hold "
        "several classical variants (paper, Sect. 4.6)."
    )
    ct = view_variant_crosstab(log, views)
    st.dataframe(ct.style.background_gradient(cmap="Blues", axis=None), width="stretch")


# --------------------------------------------------------------------------- #
# Compare tab
# --------------------------------------------------------------------------- #
with tab_compare:
    st.subheader("One global model vs. one model per view")
    _mode_expl = {
        "identifier": "the view abstraction identifier turned into a process tree (deterministic, no mining)",
        "translucent_im": "the translucent Inductive Miner on the view sub-log",
        "classic_im": "the classical Inductive Miner on the view sub-log",
    }[view_mode]
    st.markdown(
        f"- **Global model** — the translucent Inductive Miner (`{miner_variant}`, "
        f"noise `{noise:.2f}`) on the **whole log**; that one model is then scored "
        f"on each view's sub-log (`scope = global`).\n"
        f"- **Per-view model** — one per view, built from the sidebar *Per-view "
        f"model* = `{view_mode}` ({_mode_expl}), scored on its own sub-log "
        f"(`scope = per-view`).\n"
        f"- **`AGGREGATE`** — per scope, the `case_weight`-weighted mean of that "
        f"scope's rows (`case_weight = view cases / total cases`): the score an "
        f"average case sees under that approach. The two `AGGREGATE` rows are the "
        f"head-to-head."
    )
    translucent_cc = st.checkbox(
        "also compute translucent fitness / precision (enabled-set aware, slower)"
    )
    if translucent_cc:
        from tpv.quality.translucent import available as _tc_available

        _msg = _tc_available()
        if _msg:
            st.warning(_msg)
            translucent_cc = False
    if st.button("Compute conformance", type="primary"):
        st.session_state["compare_frame"] = _compare_frame(
            log, log_key, view_mode, miner_variant, noise, translucent_cc
        )
    frame = st.session_state.get("compare_frame")
    if frame is not None:
        present = [
            c
            for c in ["fitness", "precision", "generalization", "simplicity",
                      "translucent_fitness", "translucent_precision", "case_weight"]
            if c in frame.columns
        ]
        grad = [c for c in ["fitness", "precision", "simplicity",
                            "translucent_fitness", "translucent_precision"] if c in frame.columns]
        st.dataframe(
            frame.style.format({c: "{:.3f}" for c in present}).background_gradient(
                cmap="Blues", subset=grad
            ),
            width="stretch",
        )
        agg = frame[frame["view"] == "AGGREGATE"].set_index("scope")
        metrics = [m for m in ["fitness", "precision", "simplicity",
                               "translucent_fitness", "translucent_precision"] if m in agg.columns]
        cols = st.columns(len(metrics))
        for col, metric in zip(cols, metrics):
            g, p = agg.loc["global", metric], agg.loc["per-view", metric]
            col.metric(f"{metric}", f"{p:.3f}", f"{p - g:+.3f} vs global")

    st.divider()
    st.markdown("**The global model** (one model, `scope = global` rows)")
    gtree = discover_process_tree(log, variant=miner_variant, noise_threshold=noise)
    try:
        gsvg = _view_tree_svg(f"GLOBAL|{log_key}|{miner_variant}|{noise}", gtree, model_kind)
        st.image(gsvg, width="stretch")
    except Exception as exc:  # pragma: no cover
        st.warning(f"Could not render {model_kind} model: {exc}")
        st.code(str(gtree))

    st.markdown(
        f"**The per-view models** ({len(views)} models, `scope = per-view` rows; "
        f"mode `{view_mode}`) — there is no single merged per-view model, the "
        "per-view approach *is* this set of models, one per process view."
    )
    for v in views:
        with st.expander(
            f"{v.label} · {v.frequency} cases · {v.identifier.canonical_str()}",
            expanded=len(views) <= 3,
        ):
            vtree = view_process_tree(
                v, mode=view_mode, variant=miner_variant, noise_threshold=noise
            )
            try:
                st.image(
                    _view_tree_svg(f"CMP|{v.key}|{view_mode}|{miner_variant}|{noise}",
                                   vtree, model_kind),
                    width="stretch",
                )
            except Exception as exc:  # pragma: no cover
                st.warning(f"Could not render {model_kind} model: {exc}")
                st.code(str(vtree))


# --------------------------------------------------------------------------- #
# Export tab
# --------------------------------------------------------------------------- #
with tab_export:
    st.subheader("Downloads")
    summary = pd.DataFrame(
        [
            {
                "view": v.label,
                "cases": v.frequency,
                "classical_variants": v.n_variants,
                "translucent_traces": v.n_translucent_traces,
                "identifier": v.identifier.canonical_str(),
            }
            for v in views
        ]
    )
    st.dataframe(summary, width="stretch")
    st.download_button("views.csv", summary.to_csv(index=False), "views.csv", "text/csv")

    for v in views:
        buff = Path(st.session_state["_tmpdir"]) / f"{v.label}.xes"
        tio.export_xes(v.sublog, str(buff), enabled_key=enabled_key, separator=separator)
        st.download_button(
            f"{v.label} sub-log (XES)",
            buff.read_bytes(),
            file_name=f"{log.name}-{v.label}.xes",
            mime="application/xml",
            key=f"dl-{v.label}",
        )
