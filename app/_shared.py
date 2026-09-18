"""Helpers shared by the Streamlit landing page and the Task-mining page."""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# project importable when launched via `streamlit run app/streamlit_app.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
os.environ.setdefault("PM4PY_SHOW_PROGRESS_BAR", "False")

import streamlit as st

try:
    from pm4py.util import constants as _pm_constants

    _pm_constants.SHOW_PROGRESS_BAR = False
except Exception:  # pragma: no cover
    pass

from tpv.log.types import TranslucentLog
from tpv.views.views import ProcessView, induce_views
from tpv.viz.models import model_svg
from tpv.viz.variants import render_log

ACCENT = "#4C78A8"


def scratch_dir() -> str:
    if "_tmpdir" not in st.session_state:
        st.session_state["_tmpdir"] = tempfile.mkdtemp(prefix="tpv-")
    return st.session_state["_tmpdir"]


@st.cache_data(show_spinner=True)
def cached_views(_log: TranslucentLog, key: str):
    return induce_views(_log)


@st.cache_data(show_spinner=True)
def cached_model_svg(cache_key: str, _tree, kind: str) -> str:
    return model_svg(_tree, kind)


def kpi_row(log: TranslucentLog, views) -> None:
    k = st.columns(6)
    k[0].metric("Cases", log.n_cases)
    k[1].metric("Events", log.n_events)
    k[2].metric("Activities", len(log.activities))
    k[3].metric("Classical variants", len(log.classical_variants()))
    k[4].metric("Translucent variants", len(log.trace_set()))
    k[5].metric("Process views", len(views))


def variant_explorer(
    log: TranslucentLog, traces=None, labels=None, show_kappa=True, max_rows: int = 40
) -> None:
    html, height = render_log(
        log,
        traces=traces,
        accent=ACCENT,
        labels=labels,
        show_kappa=show_kappa,
        max_rows=max_rows,
    )
    st.components.v1.html(html, height=height + 8, scrolling=True)


__all__ = [
    "ACCENT",
    "scratch_dir",
    "cached_views",
    "cached_model_svg",
    "kpi_row",
    "variant_explorer",
]
