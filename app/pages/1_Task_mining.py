"""Task-mining case study -- hidden user roles in a UI-interaction log.

Mirrors the paper's Sect. 5 setting: translucent event data captured from a user
interface, where an event's enabled activities are the actions clickable on
screen and the hidden context is the user's *role*, which a screenshot does not
record.  The relationship-induced abstraction should split the log into one
process view per role even when the executed click sequences coincide.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # app/

import pandas as pd
import streamlit as st

from _shared import (
    ACCENT,
    cached_model_svg,
    cached_views,
    kpi_row,
    scratch_dir,
    variant_explorer,
)
from tpv.discovery.api import discover_process_tree, view_process_tree
from tpv.log import io as tio
from tpv.log.tasks import HELPDESK_ACTIONS, helpdesk_screen_map, task_mining_helpdesk
from tpv.quality.metrics import global_vs_views
from tpv.viz.identifier_viz import identifier_svg

st.set_page_config(page_title="Task mining · Translucent Process Views", layout="wide")

st.title("Task-mining case study")
st.markdown(
    "A helpdesk agent and a supervisor work the same ticket screen. The "
    "**executed** clicks can be identical, but the supervisor also sees "
    "`escalate` and `approve_refund` on screen. That difference lives only in "
    "the *enabled* activities — not in a screenshot, not in a classical event "
    "log — and it is what `kappa` uses to separate the two hidden process views."
)

# --------------------------------------------------------------------------- #
# sidebar
# --------------------------------------------------------------------------- #
st.sidebar.header("Task-mining log")
mode = st.sidebar.radio("Source", ["Synthetic helpdesk", "Upload XES / CSV"])
enabled_key = st.sidebar.text_input("Enabled-activities attribute", "enabled_activities")
separator = st.sidebar.text_input("Separator", ",")

ground_truth = None
if mode == "Synthetic helpdesk":
    n_agent = st.sidebar.slider("agent cases", 10, 200, 80, 10)
    n_super = st.sidebar.slider("supervisor cases", 10, 200, 55, 5)
    rework = st.sidebar.toggle("agent rework loop (extra request_info step)", value=False)
    noise = st.sidebar.slider("enabled-set noise", 0.0, 0.5, 0.0, 0.05)
    log, ground_truth = task_mining_helpdesk(
        n_agent, n_super, noise=noise, rework=rework
    )
else:
    rework = False
    up = st.sidebar.file_uploader("Task-mining log", type=["xes", "csv", "gz"])
    if up is None:
        st.info("Upload a task-mining translucent log (enabled activities = the UI "
                "actions available at each step).")
        st.stop()
    tmp = Path(scratch_dir()) / up.name
    tmp.write_bytes(up.getvalue())
    if tmp.suffix.lower() in (".xes", ".gz"):
        log = tio.load_xes(str(tmp), enabled_key=enabled_key, separator=separator)
    else:
        log = tio.load_csv(str(tmp), enabled_key=enabled_key or None, separator=separator)

view_model_mode = st.sidebar.selectbox(
    "Per-view model", ["identifier", "translucent_im", "classic_im"]
)
model_kind = st.sidebar.selectbox("Model diagram", ["petri", "tree", "bpmn"])

key = f"tm|{log.name}|{log.n_cases}|{log.n_events}"
views = cached_views(log, key)

# case_id -> discovered view label
trace_to_view = {t: v.label for v in views for t in v.traces}
case_to_view = {
    cid: trace_to_view[t] for t in log.trace_set() for cid in log.case_ids[t]
}

kpi_row(log, views)
st.divider()


# --------------------------------------------------------------------------- #
# screen map
# --------------------------------------------------------------------------- #
def enabled_union(view) -> set:
    s: set = set()
    for t in view.traces:
        for _a, enabled in t:
            s |= set(enabled)
    return s


st.subheader("Screen map — which UI actions are available to whom")
if mode == "Synthetic helpdesk":
    smap = helpdesk_screen_map(rework)
    rows = []
    for state, per_role in smap.items():
        for action in HELPDESK_ACTIONS:
            a = action in per_role["agent"]
            s = action in per_role["supervisor"]
            if not (a or s):
                continue
            rows.append(
                {
                    "screen state": state,
                    "action": action,
                    "visibility": "both" if a and s else ("agent only" if a else "supervisor only"),
                }
            )
    grid = pd.DataFrame(rows)
    pivot = grid.pivot(index="action", columns="screen state", values="visibility").fillna("—")
    st.dataframe(
        pivot.style.map(
            lambda v: {
                "both": "background-color:#4C78A833",
                "agent only": "background-color:#54A24B44",
                "supervisor only": "background-color:#F5851844",
            }.get(v, "")
        ),
        width="stretch",
    )
else:
    st.caption("Derived from the log: the actions ever enabled within each discovered view.")
    all_actions = sorted(log.activities)
    unions = {v.label: enabled_union(v) for v in views}
    tbl = pd.DataFrame(
        {lbl: [("✓" if a in u else "") for a in all_actions] for lbl, u in unions.items()},
        index=all_actions,
    )
    st.dataframe(tbl, width="stretch")


# --------------------------------------------------------------------------- #
# discovered views
# --------------------------------------------------------------------------- #
st.divider()
st.subheader("Discovered process views")

others_union = {
    v.label: set().union(*(enabled_union(o) for o in views if o.label != v.label))
    if len(views) > 1
    else set()
    for v in views
}

cols = st.columns(max(1, min(len(views), 3)))
for i, v in enumerate(views):
    distinguishing = sorted(enabled_union(v) - others_union[v.label])
    with cols[i % len(cols)].container(border=True):
        st.markdown(
            f"**{v.label}** — `{v.frequency}` cases, `{v.n_variants}` classical / "
            f"`{v.n_translucent_traces}` translucent variants"
        )
        st.progress(v.coverage(log.n_cases))
        st.code(v.identifier.canonical_str(), language="text")
        if distinguishing:
            st.caption("Only here (enabled): " + ", ".join(f"`{a}`" for a in distinguishing))

pick = st.radio("Inspect", [v.label for v in views], horizontal=True)
selected = next(v for v in views if v.label == pick)
left, right = st.columns([1, 1], gap="large")
with left:
    st.markdown("**Abstraction identifier**")
    st.image(identifier_svg(selected.identifier), width="stretch")
with right:
    st.markdown("**Discovered model**")
    tree = view_process_tree(selected, mode=view_model_mode)
    try:
        st.image(
            cached_model_svg(f"{selected.key}|{view_model_mode}|{model_kind}", tree, model_kind),
            width="stretch",
        )
    except Exception as exc:  # pragma: no cover
        st.warning(f"model render failed: {exc}")
        st.code(str(tree))


# --------------------------------------------------------------------------- #
# recovery vs. ground-truth role
# --------------------------------------------------------------------------- #
if ground_truth is not None:
    st.divider()
    st.subheader("Role recovery")
    conf = pd.crosstab(
        pd.Series({c: case_to_view[c] for c in ground_truth}, name="discovered view"),
        pd.Series(ground_truth, name="true role"),
    )
    c1, c2 = st.columns([2, 1])
    c1.dataframe(conf.style.background_gradient(cmap="Blues", axis=None), width="stretch")

    from tpv.quality.agreement import adjusted_rand_index, label_accuracy

    keys = list(ground_truth)
    truth = [ground_truth[k] for k in keys]
    pred = [case_to_view[k] for k in keys]
    ari = adjusted_rand_index(truth, pred)
    c2.metric("Adjusted Rand index", f"{ari:.3f}")
    c2.metric("Role accuracy", f"{label_accuracy(truth, pred):.1%}")
    if ari < 0.999:
        c2.caption("Noise perturbs the enabled sets, so `kappa` over-segments — more views than roles.")


# --------------------------------------------------------------------------- #
# merged vs. per-view
# --------------------------------------------------------------------------- #
st.divider()
st.subheader("One merged model vs. one model per view")
st.caption(
    "The **merged/global** model is the translucent Inductive Miner (IMtf) on the "
    "whole log; the **per-view** model uses the sidebar's *Per-view model* setting "
    f"(`{view_model_mode}`), one per view, scored on its own sub-log. "
    "`AGGREGATE` = case-weighted mean per scope (`case_weight = view cases / total`)."
)
tcc = st.checkbox("also translucent fitness / precision (enabled-set aware, slower)")
if tcc:
    from tpv.quality.translucent import available as _tc_available

    _msg = _tc_available()
    if _msg:
        st.warning(_msg)
        tcc = False
if st.button("Compute conformance", type="primary"):
    st.session_state["tm_frame"] = global_vs_views(
        log, views, view_mode=view_model_mode, translucent=tcc
    )
frame = st.session_state.get("tm_frame")
if frame is not None:
    present = [
        c for c in ["fitness", "precision", "generalization", "simplicity",
                    "translucent_fitness", "translucent_precision", "case_weight"]
        if c in frame.columns
    ]
    grad = [c for c in ["fitness", "precision", "simplicity",
                        "translucent_fitness", "translucent_precision"] if c in frame.columns]
    st.dataframe(
        frame.style.format({c: "{:.3f}" for c in present}).background_gradient(cmap="Blues", subset=grad),
        width="stretch",
    )
    agg = frame[frame["view"] == "AGGREGATE"].set_index("scope")
    metrics = [m for m in ["precision", "simplicity", "translucent_fitness", "translucent_precision"]
               if m in agg.columns]
    cols = st.columns(len(metrics))
    for col, metric in zip(cols, metrics):
        g, p = agg.loc["global", metric], agg.loc["per-view", metric]
        col.metric(f"{metric} (per-view agg.)", f"{p:.3f}", f"{p - g:+.3f} vs merged")

st.divider()
st.markdown("**The merged (global) model** — one model, `scope = global` rows")
_gtree = discover_process_tree(log, variant="IMtf")
try:
    st.image(
        cached_model_svg(f"TM-GLOBAL|{key}|{model_kind}", _gtree, model_kind),
        width="stretch",
    )
except Exception as exc:  # pragma: no cover
    st.warning(f"model render failed: {exc}")
    st.code(str(_gtree))

st.markdown(
    f"**The per-view models** — {len(views)} models (`scope = per-view` rows, mode "
    f"`{view_model_mode}`); the per-view approach is this set of models, not a "
    "single merged one."
)
for v in views:
    with st.expander(f"{v.label} · {v.frequency} cases · {v.identifier.canonical_str()}", expanded=True):
        _vtree = view_process_tree(v, mode=view_model_mode)
        try:
            st.image(
                cached_model_svg(f"TM-CMP|{v.key}|{view_model_mode}|{model_kind}", _vtree, model_kind),
                width="stretch",
            )
        except Exception as exc:  # pragma: no cover
            st.warning(f"model render failed: {exc}")
            st.code(str(_vtree))


# --------------------------------------------------------------------------- #
# variant explorer + export
# --------------------------------------------------------------------------- #
st.divider()
st.subheader("Translucent variant explorer")
variant_explorer(log, labels={t: trace_to_view[t] for t in log.trace_set()})

st.divider()
st.subheader("Export")
summary = pd.DataFrame(
    [
        {
            "view": v.label,
            "cases": v.frequency,
            "classical_variants": v.n_variants,
            "identifier": v.identifier.canonical_str(),
        }
        for v in views
    ]
)
st.download_button("views.csv", summary.to_csv(index=False), "task_mining_views.csv", "text/csv")
for v in views:
    buff = Path(scratch_dir()) / f"tm-{v.label}.xes"
    tio.export_xes(v.sublog, str(buff), enabled_key=enabled_key, separator=separator)
    st.download_button(
        f"{v.label} sub-log (XES)",
        buff.read_bytes(),
        file_name=f"{log.name}-{v.label}.xes",
        mime="application/xml",
        key=f"tmdl-{v.label}",
    )
