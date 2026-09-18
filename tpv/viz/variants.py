"""Translucent variant visualisation.

Renders each translucent trace as a row of position cells.  Every cell shows the
enabled activities as chips; the executed one is filled and underlined (the
paper's ``b-underline c d e`` notation), the alternatives are ghosted.  The local
choice set (Definition 4.3) is outlined, and every parallel-supported interval of
the left-to-right decomposition (Definitions 4.7 / 4.8) gets a bracket labelled
with the ``and(...)`` block it produces.  ``kappa`` for the trace is printed
underneath.  ``render_log`` returns ``(html, pixel_height)`` so the embedding
iframe can be sized exactly and nothing is clipped.
"""

from __future__ import annotations

import html
from typing import Iterable, List, Optional, Sequence, Tuple

from tpv.log.types import TranslucentLog, TranslucentTrace, pi_act, pi_en
from tpv.views.abstraction import (
    interval_abstraction,
    kappa,
    local_choice_set,
    parallel_decomposition,
)
from tpv.viz.theme import GHOST, activity_colors, text_on

_CELL_W = 60
_GAP = 8
_CHIP_H = 23  # line height of one stacked chip
_MAX_IFRAME_H = 1800  # above this the iframe scrolls instead of growing

_CSS = f"""
<style>
 .tv-wrap{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
   color:var(--text,#1a1a1a);padding:30px 4px 8px;box-sizing:border-box;}}
 .tv-legend{{font-size:11px;opacity:.7;margin:0 0 6px;}}
 .tv-row{{border-top:1px solid rgba(128,128,128,.25);padding:16px 0 12px;}}
 .tv-row:first-of-type{{border-top:none;}}
 .tv-head{{display:flex;gap:10px;align-items:baseline;font-size:12px;margin-bottom:6px;
   flex-wrap:wrap;}}
 .tv-head b{{font-size:13px;}}
 .tv-head .seq{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;opacity:.8;}}
 .tv-head .cnt{{opacity:.55;}}
 .tv-scroll{{overflow-x:auto;padding-bottom:6px;}}
 .tv-stack{{display:inline-flex;flex-direction:column;min-width:100%;}}
 .tv-bracket{{position:relative;height:26px;}}
 .tv-band{{position:absolute;top:12px;height:12px;border:2px solid var(--acc,#4C78A8);
   border-bottom:none;border-radius:6px 6px 0 0;box-sizing:border-box;}}
 .tv-band-lbl{{position:absolute;left:0;top:-2px;transform:translateY(-100%);
   font-size:10px;font-family:ui-monospace,monospace;color:var(--acc,#4C78A8);
   white-space:nowrap;}}
 .tv-cells{{display:flex;gap:{_GAP}px;}}
 .tv-cell{{display:flex;flex-direction:column;align-items:center;gap:4px;
   width:{_CELL_W}px;flex:0 0 {_CELL_W}px;}}
 .tv-pos{{font-size:10px;opacity:.45;}}
 .tv-chips{{display:flex;flex-direction:column;gap:3px;padding:5px;border-radius:8px;
   border:1.5px dashed transparent;width:100%;box-sizing:border-box;align-items:center;}}
 .tv-chips.choice{{border-color:rgba(120,120,120,.85);background:rgba(128,128,128,.06);}}
 .tv-chip{{font-size:11px;font-weight:600;padding:2px 7px;border-radius:999px;
   border:1px solid rgba(128,128,128,.4);color:#8a8a8a;white-space:nowrap;
   max-width:100%;overflow:hidden;text-overflow:ellipsis;}}
 .tv-chip.exec{{border-color:transparent;text-decoration:underline;
   text-underline-offset:2px;font-weight:800;}}
 .tv-kappa{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
   opacity:.8;margin-top:8px;white-space:nowrap;}}
 .tv-more{{font-size:11px;opacity:.6;padding:10px 0 0;}}
</style>
"""


def _chip(activity: str, executed: bool, color: str) -> str:
    label = html.escape(activity)
    if executed:
        return (
            f'<span class="tv-chip exec" style="background:{color};'
            f'color:{text_on(color)};">{label}</span>'
        )
    return f'<span class="tv-chip" style="border-color:{GHOST};">{label}</span>'


def _enabled_list(trace: TranslucentTrace, pos: int, universe) -> List[str]:
    event = trace[pos - 1]
    executed = pi_act(event)
    enabled = [a for a in universe if a in pi_en(event)]
    if executed not in enabled:
        enabled = [executed] + enabled
    return enabled or [executed]


def _cell(trace: TranslucentTrace, pos: int, universe, colors) -> str:
    executed = pi_act(trace[pos - 1])
    enabled = _enabled_list(trace, pos, universe)
    chips = "".join(_chip(a, a == executed, colors.get(a, "#4C78A8")) for a in enabled)
    cls = "tv-chips choice" if len(local_choice_set(trace, pos)) > 1 else "tv-chips"
    return (
        f'<div class="tv-cell"><div class="tv-pos">{pos}</div>'
        f'<div class="{cls}">{chips}</div></div>'
    )


def _bracket_row(trace: TranslucentTrace, accent: str) -> Tuple[str, bool]:
    spans = []
    for interval in parallel_decomposition(trace):
        if len(interval) < 2:
            continue
        p, q = interval[0], interval[-1]
        left = (p - 1) * (_CELL_W + _GAP)
        width = (q - p + 1) * _CELL_W + (q - p) * _GAP
        label = html.escape(interval_abstraction(trace, interval).canonical_str())
        spans.append(
            f'<div class="tv-band" style="left:{left}px;width:{width}px;--acc:{accent};">'
            f'<span class="tv-band-lbl" style="--acc:{accent};">{label}</span></div>'
        )
    if not spans:
        return "", False
    total = len(trace) * (_CELL_W + _GAP)
    return f'<div class="tv-bracket" style="width:{total}px;">' + "".join(spans) + "</div>", True


def _row_height(trace: TranslucentTrace, universe, show_kappa: bool, has_bracket: bool) -> int:
    max_chips = max((len(_enabled_list(trace, i, universe)) for i in range(1, len(trace) + 1)), default=1)
    cells_h = 14 + 10 + max_chips * _CHIP_H  # pos label + chip padding + stacked chips
    return (
        16  # row padding-top
        + (26 if has_bracket else 0)
        + 24  # head line
        + cells_h
        + (20 if show_kappa else 0)
        + 12  # row padding-bottom
        + 12  # scrollbar allowance
    )


def render_trace_row(
    trace: TranslucentTrace,
    universe: Sequence[str],
    colors: dict,
    head_html: str = "",
    accent: str = "#4C78A8",
    show_kappa: bool = True,
) -> Tuple[str, int]:
    bracket, has_bracket = _bracket_row(trace, accent)
    cells = "".join(_cell(trace, i, universe, colors) for i in range(1, len(trace) + 1))
    kappa_html = (
        f'<div class="tv-kappa">&kappa; = {html.escape(kappa(trace).canonical_str())}</div>'
        if show_kappa
        else ""
    )
    html_row = (
        '<div class="tv-row">'
        f'<div class="tv-head">{head_html}</div>'
        '<div class="tv-scroll"><div class="tv-stack">'
        f"{bracket}"
        f'<div class="tv-cells">{cells}</div>'
        f"{kappa_html}"
        "</div></div></div>"
    )
    return html_row, _row_height(trace, universe, show_kappa, has_bracket)


def render_log(
    log: TranslucentLog,
    traces: Optional[Iterable[TranslucentTrace]] = None,
    accent: str = "#4C78A8",
    labels: Optional[dict] = None,
    show_kappa: bool = True,
    max_rows: int = 40,
) -> Tuple[str, int]:
    """Return ``(html, pixel_height)`` for the translucent variant explorer.

    At most ``max_rows`` traces are drawn (a note is added when more exist); the
    returned height is capped so very long logs scroll inside the iframe.
    """
    universe = sorted(log.activities)
    colors = activity_colors(universe)
    all_traces = list(traces) if traces is not None else log.trace_set()
    all_traces = sorted(all_traces, key=lambda t: -log.variants.get(t, 0))
    shown = all_traces[:max_rows]

    rows: List[str] = []
    height = 100  # wrap padding + legend
    for trace in shown:
        n_cases = log.variants.get(trace, 0)
        exec_seq = " ".join(pi_act(e) for e in trace) or "(empty)"
        label = (labels or {}).get(trace, "")
        head = (
            (f"<b>{html.escape(label)}</b>" if label else "<b>trace</b>")
            + f'<span class="seq">{html.escape(exec_seq)}</span>'
            + f'<span class="cnt">{n_cases} case(s)</span>'
        )
        row_html, row_h = render_trace_row(trace, universe, colors, head, accent, show_kappa)
        rows.append(row_html)
        height += row_h

    if len(all_traces) > len(shown):
        rows.append(
            f'<div class="tv-more">… {len(all_traces) - len(shown)} more translucent '
            f"variant(s) not shown (of {len(all_traces)} total).</div>"
        )
        height += 30

    legend = (
        '<div class="tv-legend">Filled + underlined = executed &nbsp;|&nbsp; '
        "ghost = enabled alternative &nbsp;|&nbsp; dashed box = local choice set "
        "(Def. 4.3) &nbsp;|&nbsp; bracket = parallel-supported interval (Def. 4.7/4.8)"
        "</div>"
    )
    doc = _CSS + '<div class="tv-wrap">' + legend + "".join(rows) + "</div>"
    return doc, min(height, _MAX_IFRAME_H)


__all__ = ["render_log", "render_trace_row"]
