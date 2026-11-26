"""SUPERSEDED by ``make_servicedesk_petrinets.py`` -- the case-study figure is
now the discovered Petri nets (one global model + the four per-view models kappa
induces) rather than this hand-drawn control-flow diagram. Kept for reference.

Vector figure of the IT-ServiceDesk desktop workflow used in the paper's
scenario-based case study (Sect. 5.4).

Draws the base control-flow (start -> open -> triage block -> diagnosis block ->
action choice -> close choice -> log_time -> notify -> end) plus a table of how
the four hidden roles vary it (parallel / sequential / skipped blocks and the
role-gated on-screen actions).  Emits an SVG always and a PDF if reportlab is
installed -- same backend-agnostic primitive model as
``make_request_handling_mockup.py``.

Run:  python figures/make_servicedesk_workflow.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1780, 560
FONT = "Inter, 'Helvetica Neue', Arial, sans-serif"

C_BG = "#FFFFFF"
C_HEAD = "#101828"
C_MUTED = "#475467"
C_FAINT = "#98A2B3"
C_ACT = "#2563EB"        # activity box (blue, = "enabled" in the mockup)
C_ACT_T = "#FFFFFF"
C_GATE = "#F1F3F5"       # gateway diamond
C_GATE_S = "#98A2B3"
C_GATE_T = "#344054"
C_ACCENT = "#067647"     # green accent (= "executed")
C_ARROW = "#667085"
C_TBL_HEAD = "#EEF2FF"
C_TBL_BORDER = "#D0D5DD"
C_HAIRLINE = "#E4E7EC"


# ----------------------------------------------------------------------------- #
# primitives (identical model to make_request_handling_mockup.py)
# ----------------------------------------------------------------------------- #
def _text_w(s: str, size: float) -> float:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(s, "Helvetica", size)
    except Exception:
        return len(s) * size * 0.52


def rect(out, x, y, w, h, r, fill, stroke=None, sw=1):
    out.append(("rect", x, y, w, h, r, fill, stroke, sw))


def line(out, x1, y1, x2, y2, stroke, sw=1, caps="butt"):
    out.append(("line", x1, y1, x2, y2, stroke, sw, caps))


def circle(out, cx, cy, rad, fill, stroke=None, sw=1):
    out.append(("circle", cx, cy, rad, fill, stroke, sw))


def poly(out, pts, fill, stroke=None, sw=1):
    out.append(("poly", tuple(pts), fill, stroke, sw))


def text(out, x, y, s, size, fill, weight="400", anchor="start", italic=False, vcenter=False):
    out.append(("text", x, y, s, size, fill, weight, anchor, italic, vcenter))


def arrow(out, x1, y, x2, ay=None):
    ay = y if ay is None else ay
    line(out, x1, y, x2 - 7, ay, C_ARROW, 1.6, "round")
    poly(out, [(x2, ay), (x2 - 9, ay - 4.5), (x2 - 9, ay + 4.5)], C_ARROW)


# ----------------------------------------------------------------------------- #
# composite: the base flow + the role table
# ----------------------------------------------------------------------------- #
BOX_H = 40
FLOW_Y = 150
GATE = 46


def _abox(out, x, w, label, sub=None):
    rect(out, x, FLOW_Y - BOX_H / 2, w, BOX_H, 9, C_ACT)
    text(out, x + w / 2, FLOW_Y, label, 13, C_ACT_T, weight="600", anchor="middle",
         vcenter=True)
    if sub:
        text(out, x + w / 2, FLOW_Y + BOX_H / 2 + 15, sub, 10.5, C_FAINT, anchor="middle")


def _gate(out, cx, kind, caption):
    d = GATE / 2
    poly(out, [(cx, FLOW_Y - d), (cx + d, FLOW_Y), (cx, FLOW_Y + d), (cx - d, FLOW_Y)],
         C_GATE, C_GATE_S, 1.4)
    text(out, cx, FLOW_Y + 1, "+" if kind == "and" else "×", 20, C_GATE_T,
         weight="700", anchor="middle", vcenter=True)
    text(out, cx, FLOW_Y - d - 10, caption, 10.5, C_MUTED, anchor="middle")


def build_shapes():
    out = [("rect", 0, 0, W, H, 0, C_BG, None, 0)]
    text(out, 48, 54, "IT ServiceDesk - base desktop workflow", 22, C_HEAD, weight="700")
    text(out, 48, 78, "Hidden context = the operator's role. Blocks run in parallel (+), "
                      "in sequence, or are skipped depending on the role.", 12.5, C_MUTED)

    x = 56
    circle(out, x, FLOW_Y, 12, "#FFFFFF", C_ARROW, 2)
    x += 22
    arrow(out, x, FLOW_Y, x + 18); x += 18
    _abox(out, x, 72, "open"); x += 72
    arrow(out, x, FLOW_Y, x + 22); x += 22
    _gate(out, x + GATE / 2, "and", "triage"); x += GATE
    _abox(out, x + 10, 190, "categorize  ->  set_priority", "block"); x += 10 + 190 + 10
    arrow(out, x, FLOW_Y, x + 20); x += 20
    _gate(out, x + GATE / 2, "and", "diagnosis"); x += GATE
    _abox(out, x + 10, 214, "check_kb || run_diag || remote", "block"); x += 10 + 214 + 10
    arrow(out, x, FLOW_Y, x + 20); x += 20
    _gate(out, x + GATE / 2, "xor", "action"); x += GATE
    _abox(out, x + 10, 174, "apply_fix | request_info", "( + escalate / approve )")
    x += 10 + 174 + 10
    arrow(out, x, FLOW_Y, x + 20); x += 20
    _gate(out, x + GATE / 2, "xor", "close"); x += GATE
    _abox(out, x + 10, 240, "resolve | close_noaction | force_close", "block")
    x += 10 + 240 + 10
    arrow(out, x, FLOW_Y, x + 20); x += 20
    _abox(out, x, 132, "log_time  ->  notify"); x += 132
    arrow(out, x, FLOW_Y, x + 18); x += 18
    circle(out, x + 12, FLOW_Y, 12, "#FFFFFF", C_ARROW, 2)
    circle(out, x + 12, FLOW_Y, 6, C_ARROW)

    # ---- role-variation table --------------------------------------------- #
    ty = 300
    text(out, 48, ty - 14, "Per-role variation of the base flow", 15, C_HEAD, weight="700")
    cols = [("Role", 150), ("Triage", 150), ("Diagnosis", 250), ("On screen", 230),
            ("Close", 300)]
    rows = [
        ("L1 agent", "sequential", "check_kb", "—",
         "resolve"),
        ("L2 senior", "parallel", "check_kb || run_diag || remote", "escalate",
         "resolve | close_noaction"),
        ("L3 specialist", "skipped", "run_diag || remote", "escalate",
         "skipped (hand back)"),
        ("supervisor", "parallel", "check_kb", "approve, force_close",
         "resolve | close_noaction | force_close"),
    ]
    tx = 48
    x0 = tx
    rh = 34
    # header
    total_w = sum(w for _, w in cols)
    rect(out, x0, ty, total_w, rh, 6, C_TBL_HEAD, C_TBL_BORDER, 1)
    cx = x0
    for name, w in cols:
        text(out, cx + 12, ty + rh / 2, name, 12, C_HEAD, weight="700", vcenter=True)
        cx += w
    # body
    for i, row in enumerate(rows):
        ry = ty + rh + i * rh
        rect(out, x0, ry, total_w, rh, 0, "#FFFFFF" if i % 2 else "#FBFCFE",
             C_HAIRLINE, 1)
        cx = x0
        for j, (cell, (_, w)) in enumerate(zip(row, cols)):
            col = C_HEAD if j == 0 else C_MUTED
            wt = "600" if j == 0 else "400"
            if cell in ("skipped", "skipped (hand back)"):
                col = "#B42318"
            if j == 3 and cell != "—":
                col = C_ACCENT
            text(out, cx + 12, ry + rh / 2, cell, 11.5, col, weight=wt, vcenter=True)
            cx += w
    rect(out, x0, ty, total_w, rh + len(rows) * rh, 6, "none", C_TBL_BORDER, 1)

    # ---- legend --------------------------------------------------------- #
    ly = ty + rh + len(rows) * rh + 44
    rect(out, tx, ly - 12, 26, 18, 5, C_ACT)
    text(out, tx + 34, ly, "activity / block", 11.5, C_MUTED, vcenter=True)
    poly(out, [(tx + 175, ly - 11), (tx + 186, ly - 2), (tx + 175, ly + 7), (tx + 164, ly - 2)],
         C_GATE, C_GATE_S, 1.2)
    text(out, tx + 196, ly, "gateway:  +  parallel (AND),   ×  choice (XOR)", 11.5,
         C_MUTED, vcenter=True)
    text(out, tx + 470, ly, "|| = concurrent    | = exclusive choice", 11.5, C_FAINT,
         vcenter=True)
    text(out, tx, ly + 26,
         "Enabled activities are read from screenshots; the action screen's menu carries the "
         "role's gated options, so kappa sees a per-role enabled signature.", 11, C_FAINT,
         italic=True)
    return out


# ----------------------------------------------------------------------------- #
# emitters
# ----------------------------------------------------------------------------- #
def emit_svg(shapes) -> str:
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}">']
    for sh in shapes:
        k = sh[0]
        if k == "rect":
            _, x, y, w, h, r, fill, stroke, sw = sh
            s = (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'rx="{r}" ry="{r}" fill="{fill}"')
            if stroke and stroke != "none":
                s += f' stroke="{stroke}" stroke-width="{sw}"'
            if fill == "none":
                s = s.replace('fill="none"', 'fill="none"')
            p.append(s + "/>")
        elif k == "line":
            _, x1, y1, x2, y2, stroke, sw, caps = sh
            p.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{stroke}" stroke-width="{sw}" stroke-linecap="{caps}"/>')
        elif k == "circle":
            _, cx, cy, rad, fill, stroke, sw = sh
            s = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rad}" fill="{fill}"'
            if stroke:
                s += f' stroke="{stroke}" stroke-width="{sw}"'
            p.append(s + "/>")
        elif k == "poly":
            _, pts, fill, stroke, sw = sh
            d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            s = f'<polygon points="{d}" fill="{fill}"'
            if stroke:
                s += f' stroke="{stroke}" stroke-width="{sw}"'
            p.append(s + "/>")
        elif k == "text":
            _, x, y, s, size, fill, weight, anchor, italic, vcenter = sh
            style = f"font-family:{FONT};font-size:{size}px;font-weight:{weight}"
            if italic:
                style += ";font-style:italic"
            db = ' dominant-baseline="central"' if vcenter else ""
            p.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{db} '
                     f'style="{style}" fill="{fill}">{escape(s)}</text>')
    p.append("</svg>")
    return "\n".join(p) + "\n"


def emit_pdf(shapes, path: Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import getAscentDescent
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(W, H))

    def Y(v):
        return H - v

    for sh in shapes:
        k = sh[0]
        if k == "rect":
            _, x, y, w, h, r, fill, stroke, sw = sh
            do_s = 0
            if stroke and stroke != "none":
                c.setStrokeColor(HexColor(stroke))
                c.setLineWidth(sw)
                do_s = 1
            do_f = 0 if fill == "none" else 1
            if do_f:
                c.setFillColor(HexColor(fill))
            if r and r > 0.5:
                c.roundRect(x, Y(y + h), w, h, min(r, min(w, h) / 2), stroke=do_s, fill=do_f)
            else:
                c.rect(x, Y(y + h), w, h, stroke=do_s, fill=do_f)
        elif k == "line":
            _, x1, y1, x2, y2, stroke, sw, caps = sh
            c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(sw)
            c.setLineCap(1 if caps == "round" else 0)
            c.line(x1, Y(y1), x2, Y(y2))
            c.setLineCap(0)
        elif k == "circle":
            _, cx, cy, rad, fill, stroke, sw = sh
            c.setFillColor(HexColor(fill))
            do_s = 0
            if stroke:
                c.setStrokeColor(HexColor(stroke))
                c.setLineWidth(sw)
                do_s = 1
            c.circle(cx, Y(cy), rad, stroke=do_s, fill=1)
        elif k == "poly":
            _, pts, fill, stroke, sw = sh
            pth = c.beginPath()
            pth.moveTo(pts[0][0], Y(pts[0][1]))
            for px, py in pts[1:]:
                pth.lineTo(px, Y(py))
            pth.close()
            do_s = 0
            if stroke:
                c.setStrokeColor(HexColor(stroke))
                c.setLineWidth(sw)
                do_s = 1
            c.setFillColor(HexColor(fill))
            c.drawPath(pth, stroke=do_s, fill=1)
        elif k == "text":
            _, x, y, s, size, fill, weight, anchor, italic, vcenter = sh
            bold = weight in ("600", "700", "bold")
            font = "Helvetica-Bold" if bold else "Helvetica"
            if italic:
                font = "Helvetica-BoldOblique" if bold else "Helvetica-Oblique"
            ty = Y(y)
            if vcenter:
                asc, desc = getAscentDescent(font, size)
                ty -= (asc + desc) / 2.0
            c.setFont(font, size)
            c.setFillColor(HexColor(fill))
            if anchor == "middle":
                c.drawCentredString(x, ty, s)
            else:
                c.drawString(x, ty, s)

    c.showPage()
    c.save()


def main() -> None:
    here = Path(__file__).parent
    shapes = build_shapes()
    svg = here / "servicedesk_workflow.svg"
    svg.write_text(emit_svg(shapes), encoding="utf-8")
    print(f"wrote {svg}")
    pdf = here / "servicedesk_workflow.pdf"
    try:
        emit_pdf(shapes, pdf)
        print(f"wrote {pdf}")
    except ImportError:
        print("skipped PDF: reportlab not installed")


if __name__ == "__main__":
    main()
