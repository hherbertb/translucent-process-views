"""Generate the "Request Handling System" hidden-process-views figure.

One simplified web application rendered three times side by side.  Every panel is
the *same* request page; only the set of enabled / disabled action buttons
differs.  A user account chip in each panel's top-right names the signed-in user
whose configuration produces that action set (M / James Bond / Moneypenny).  A
bottom strip shows the final decision state common to all three views.

Writes both

    figures/request_handling_hidden_views.svg   (hand-built, no deps)
    figures/request_handling_hidden_views.pdf   (vector, via reportlab)

Run:  python figures/make_request_handling_mockup.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------- #
# canvas
# --------------------------------------------------------------------------- #
W, H = 1660, 1010
FONT = "'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif"  # SVG font stack

PANEL_W = 532
PANEL_X = (18, 566, 1114)          # left edges of panels A, B, C
LABEL_Y = 84                       # baseline of the "(A) ..." panel labels
BODY_Y = 108                       # top of each panel card
PANEL_H = 664

BAR_H = 38                         # window chrome height
CARD_PAD = 14                      # inner padding of a panel
BTN_W, BTN_H = 236, 56
GRID_GAP = 14

# --------------------------------------------------------------------------- #
# palette (flat, print-safe)
# --------------------------------------------------------------------------- #
C_BG = "#FFFFFF"
C_PANEL_BORDER = "#D0D5DD"
C_BAR = "#F2F4F7"
C_DOT = "#D0D5DD"
C_PILL = "#E9ECF2"
C_HEAD = "#1F2937"
C_MUTED = "#667085"
C_FAINT = "#98A2B3"
C_HAIRLINE = "#E4E7EC"
C_CARD = "#F9FAFB"
C_CHIP = "#EEF2FF"
C_CHIP_BORDER = "#C7D2FE"
C_CHIP_AVATAR = "#6366F1"
C_CHIP_TEXT = "#3730A3"

STATE = {
    "enabled": dict(fill="#2563EB", text="#FFFFFF", stroke=None),
    "disabled": dict(fill="#F1F3F5", text="#98A2B3", stroke="#E4E7EC"),
    "executed": dict(fill="#ECFDF3", text="#067647", stroke="#ABEFC6"),
}

ACTIVITIES = [
    "Open request (o)",
    "Budget check (b)",
    "Compliance check (c)",
    "Manager review (d)",
    "Legal review (e)",
    "Submit request (f)",
    "Approve (g)",
    "Reject (h)",
]

_E, _D, _X = "enabled", "disabled", "executed"
PANELS = [
    {
        "title": "(A) Hidden View 1: independent choices",
        "user": "M",
        "initials": "M",
        "note": "Choice b/c and choice d/e are independent.",
        "states": {
            "Open request (o)": _X, "Budget check (b)": _E, "Compliance check (c)": _E,
            "Manager review (d)": _E, "Legal review (e)": _E,
            "Submit request (f)": _D, "Approve (g)": _D, "Reject (h)": _D,
        },
    },
    {
        "title": "(B) Hidden View 2: sequential choices",
        "user": "James Bond",
        "initials": "JB",
        "note": "Choice d/e unlocks only after b/c.",
        "states": {
            "Open request (o)": _X, "Budget check (b)": _E, "Compliance check (c)": _E,
            "Manager review (d)": _D, "Legal review (e)": _D,
            "Submit request (f)": _D, "Approve (g)": _D, "Reject (h)": _D,
        },
    },
    {
        "title": "(C) Hidden View 3: restricted view",
        "user": "Moneypenny",
        "initials": "MP",
        "note": "No early alternatives are available.",
        "states": {
            "Open request (o)": _X, "Budget check (b)": _E, "Compliance check (c)": _D,
            "Manager review (d)": _D, "Legal review (e)": _D,
            "Submit request (f)": _D, "Approve (g)": _D, "Reject (h)": _D,
        },
    },
]


# --------------------------------------------------------------------------- #
# backend-agnostic drawing model: a list of primitive tuples
# --------------------------------------------------------------------------- #
def _text_w(s: str, size: float) -> float:
    """Helvetica text width in points (reportlab metrics if available)."""
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        return stringWidth(s, "Helvetica", size)
    except Exception:
        return len(s) * size * 0.52


def rect(out, x, y, w, h, r, fill, stroke=None, sw=1):
    out.append(("rect", x, y, w, h, r, fill, stroke, sw))


def line(out, x1, y1, x2, y2, stroke, sw=1, caps="butt"):
    out.append(("line", x1, y1, x2, y2, stroke, sw, caps))


def circle(out, cx, cy, rad, fill):
    out.append(("circle", cx, cy, rad, fill))


def text(out, x, y, s, size, fill, weight="400", anchor="start", italic=False,
         spacing=0, vcenter=False):
    # vcenter=True: y is the vertical CENTRE of the text, not the baseline.
    out.append(("text", x, y, s, size, fill, weight, anchor, italic, spacing, vcenter))


def check(out, cx, cy, color, s=7):
    """A small tick mark, drawn as two strokes (glyph-free, so it survives PDF)."""
    line(out, cx - s * 0.5, cy, cx - s * 0.05, cy + s * 0.55, color, 2, "round")
    line(out, cx - s * 0.05, cy + s * 0.55, cx + s * 0.95, cy - s * 0.7, color, 2, "round")


BTN_FS = 17.5  # button label font size


def button(out, x, y, label, state):
    st = STATE[state]
    rect(out, x, y, BTN_W, BTN_H, 8, st["fill"], st["stroke"], 1)
    if state == "executed":
        check(out, x + 20, y + BTN_H / 2, st["text"])
    text(out, x + BTN_W / 2, y + BTN_H / 2, label, BTN_FS, st["text"],
         weight="500", anchor="middle", vcenter=True)


# --------------------------------------------------------------------------- #
# composite pieces
# --------------------------------------------------------------------------- #
def panel(out, x, spec):
    text(out, x + 2, LABEL_Y, spec["title"], 24, C_HEAD, weight="600")

    rect(out, x, BODY_Y, PANEL_W, PANEL_H, 12, "#FFFFFF", stroke=C_PANEL_BORDER, sw=1)

    # window chrome (inset 1px so the card border stays visible along the sides)
    rect(out, x + 1, BODY_Y + 1, PANEL_W - 2, BAR_H, 11, C_BAR)
    rect(out, x + 1, BODY_Y + BAR_H - 11, PANEL_W - 2, 12, 0, C_BAR)  # square off bar bottom
    line(out, x + 1, BODY_Y + BAR_H, x + PANEL_W - 1, BODY_Y + BAR_H, C_PANEL_BORDER, 1)
    cy = BODY_Y + BAR_H / 2
    for i in range(3):
        circle(out, x + 20 + i * 18, cy, 4.5, C_DOT)
    pill_x = x + 84
    rect(out, pill_x, cy - 11, PANEL_W - 84 - 16, 22, 11, C_PILL)
    text(out, pill_x + 13, cy + 5, "/requests/1042", 15.5, C_FAINT)

    # header
    hy = BODY_Y + BAR_H + 46
    text(out, x + CARD_PAD + 4, hy, "Request Handling System", 27, C_HEAD, weight="600")

    # user indicator (account chip), top-right of the app
    user = spec["user"]
    initials = spec["initials"]
    chip_h = 30
    av_r = 11
    cyc = hy - 21 + chip_h / 2                    # chip vertical centre
    av_cx_off = chip_h / 2                        # avatar centred in the pill's left cap
    name_x_off = av_cx_off + av_r + 7
    chip_w = name_x_off + _text_w(user, 16) + 16
    chip_x = x + PANEL_W - CARD_PAD - chip_w
    rect(out, chip_x, hy - 21, chip_w, chip_h, chip_h / 2, C_CHIP, stroke=C_CHIP_BORDER, sw=1)
    circle(out, chip_x + av_cx_off, cyc, av_r, C_CHIP_AVATAR)
    text(out, chip_x + av_cx_off, cyc, initials, 12, "#FFFFFF",
         weight="600", anchor="middle", vcenter=True)
    text(out, chip_x + name_x_off, cyc, user, 16, C_CHIP_TEXT, weight="500", vcenter=True)

    line(out, x + CARD_PAD, hy + 16, x + PANEL_W - CARD_PAD, hy + 16, C_HAIRLINE, 1)

    # request card
    rc_x = x + CARD_PAD
    rc_y = hy + 34
    rc_h = 150
    rect(out, rc_x, rc_y, PANEL_W - 2 * CARD_PAD, rc_h, 10, C_CARD, stroke=C_HAIRLINE, sw=1)
    text(out, rc_x + 20, rc_y + 36, "Request #1042", 21, C_HEAD, weight="600")
    for i, field in enumerate(
        ("Type: Purchase Request", "Amount: 12,000 EUR", "Status: In Review")
    ):
        text(out, rc_x + 20, rc_y + 66 + i * 26, field, 17.5, C_MUTED)

    # actions
    ax = x + CARD_PAD
    ay = rc_y + rc_h + 32
    text(out, ax + 4, ay, "ACTIONS", 15, C_FAINT, weight="600", spacing=1.8)

    grid_y = ay + 18
    col_x = (ax, ax + BTN_W + GRID_GAP)
    for idx, label in enumerate(ACTIVITIES):
        r, c = divmod(idx, 2)
        button(out, col_x[c], grid_y + r * (BTN_H + GRID_GAP), label, spec["states"][label])

    note_y = grid_y + 4 * (BTN_H + GRID_GAP) + 16
    text(out, ax + 4, note_y, spec["note"], 16, C_MUTED, italic=True)


def decision_strip(out):
    w, h = 2 * BTN_W + GRID_GAP + 56, 168
    x = (W - w) / 2
    y = 812
    rect(out, x, y, w, h, 12, "#FFFFFF", stroke="#D0D5DD", sw=1)
    text(out, x + 26, y + 38, "Final decision state", 21, C_HEAD, weight="600")
    text(out, x + 26, y + 64, "Final choice — appears in all three views.", 16, C_MUTED)
    bx = x + (w - (2 * BTN_W + GRID_GAP)) / 2
    by = y + 86
    button(out, bx, by, "Approve (g)", "enabled")
    button(out, bx + BTN_W + GRID_GAP, by, "Reject (h)", "enabled")


def build_shapes():
    out = [("rect", 0, 0, W, H, 0, C_BG, None, 0)]
    for x, spec in zip(PANEL_X, PANELS):
        panel(out, x, spec)
    decision_strip(out)
    return out


# --------------------------------------------------------------------------- #
# emitters
# --------------------------------------------------------------------------- #
def emit_svg(shapes) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}">'
    ]
    for sh in shapes:
        k = sh[0]
        if k == "rect":
            _, x, y, w, h, r, fill, stroke, sw = sh
            s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" ry="{r}" fill="{fill}"'
            if stroke:
                s += f' stroke="{stroke}" stroke-width="{sw}"'
            parts.append(s + "/>")
        elif k == "line":
            _, x1, y1, x2, y2, stroke, sw, caps = sh
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{stroke}" stroke-width="{sw}" stroke-linecap="{caps}"/>'
            )
        elif k == "circle":
            _, cx, cy, rad, fill = sh
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rad}" fill="{fill}"/>')
        elif k == "text":
            _, x, y, s, size, fill, weight, anchor, italic, spacing, vcenter = sh
            style = f"font-family:{FONT};font-size:{size}px;font-weight:{weight}"
            if italic:
                style += ";font-style:italic"
            if spacing:
                style += f";letter-spacing:{spacing}px"
            db = ' dominant-baseline="central"' if vcenter else ""
            parts.append(
                f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{db} '
                f'style="{style}" fill="{fill}">{escape(s)}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def emit_pdf(shapes, path: Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import getAscentDescent
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(W, H))

    def Y(v):  # SVG top-left origin -> PDF bottom-left origin
        return H - v

    for sh in shapes:
        k = sh[0]
        if k == "rect":
            _, x, y, w, h, r, fill, stroke, sw = sh
            c.setFillColor(HexColor(fill))
            do_stroke = 0
            if stroke:
                c.setStrokeColor(HexColor(stroke))
                c.setLineWidth(sw)
                do_stroke = 1
            if r and r > 0.5:
                c.roundRect(x, Y(y + h), w, h, min(r, min(w, h) / 2),
                            stroke=do_stroke, fill=1)
            else:
                c.rect(x, Y(y + h), w, h, stroke=do_stroke, fill=1)
        elif k == "line":
            _, x1, y1, x2, y2, stroke, sw, caps = sh
            c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(sw)
            c.setLineCap(1 if caps == "round" else 0)
            c.line(x1, Y(y1), x2, Y(y2))
            c.setLineCap(0)
        elif k == "circle":
            _, cx, cy, rad, fill = sh
            c.setFillColor(HexColor(fill))
            c.circle(cx, Y(cy), rad, stroke=0, fill=1)
        elif k == "text":
            _, x, y, s, size, fill, weight, anchor, italic, spacing, vcenter = sh
            bold = weight in ("600", "700", "bold")
            font = "Helvetica-Bold" if bold else "Helvetica"
            if italic:
                font = "Helvetica-BoldOblique" if bold else "Helvetica-Oblique"
            ty = Y(y)
            if vcenter:  # match SVG dominant-baseline="central": glyph centre on y
                asc, desc = getAscentDescent(font, size)
                ty -= (asc + desc) / 2.0
            c.setFont(font, size)
            c.setFillColor(HexColor(fill))
            if spacing:  # letter-spacing (anchor "start" only, i.e. the ACTIONS label)
                to = c.beginText(x, ty)
                to.setFont(font, size)
                to.setFillColor(HexColor(fill))
                to.setCharSpace(spacing)
                to.textOut(s)
                to.setCharSpace(0)  # PDF Tc is graphics state; reset so it does not leak
                c.drawText(to)
            elif anchor == "middle":
                c.drawCentredString(x, ty, s)
            else:
                c.drawString(x, ty, s)

    c.showPage()
    c.save()


# --------------------------------------------------------------------------- #
def main() -> None:
    here = Path(__file__).parent
    shapes = build_shapes()

    svg_path = here / "request_handling_hidden_views.svg"
    svg_path.write_text(emit_svg(shapes), encoding="utf-8")
    print(f"wrote {svg_path}")

    pdf_path = here / "request_handling_hidden_views.pdf"
    try:
        emit_pdf(shapes, pdf_path)
        print(f"wrote {pdf_path}")
    except ImportError:
        print("skipped PDF: reportlab not installed (pip install reportlab)")


if __name__ == "__main__":
    main()
