# Figures

## `request_handling_hidden_views.svg`

Academic vector figure for the paper: one simplified "Request Handling System"
web page rendered three times, each with a different set of enabled / disabled
action buttons. Each panel carries a user account chip in the top-right corner
naming the signed-in user whose configuration produces that action set.

* (A) Hidden View 1 — *M*: after opening the request, `b`, `c`, `d`, `e` are all enabled (independent choices).
* (B) Hidden View 2 — *James Bond*: only `b`, `c` are enabled first; `d`, `e` unlock later (sequential choices).
* (C) Hidden View 3 — *Moneypenny*: only `b` is enabled (restricted view).
* Bottom strip — the final decision state (`Approve (g)` / `Reject (h)`) shared by all views.

Blue = enabled, grey = disabled, muted green with `✓` = already executed.
16:9, white background, flat vector, no external assets.

Regenerate both `request_handling_hidden_views.svg` and
`request_handling_hidden_views.pdf`:

```bash
python figures/make_request_handling_mockup.py
```

The script builds one backend-agnostic list of drawing primitives and emits the
SVG by hand (no dependency) and the PDF via `reportlab` (vector, Helvetica; the
`✓` is drawn as two strokes so it needs no glyph). Every coordinate and colour
is a named constant at the top of the file. If `reportlab` is missing the SVG is
still written and the PDF step is skipped with a message.
