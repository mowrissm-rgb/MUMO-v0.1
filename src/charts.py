"""
MUMO — Report charts (pure SVG, no plotting library)
Multi-Agent Drug Discovery & Development AI Platform
Author: Mowriss & Claude (research partner)

WHY HAND-WRITTEN SVG
--------------------
These figures go into the .docx report, which already rasterizes SVG through a
headless Chromium (report_writer.svg_to_png). Emitting SVG therefore needs NO
new dependency — and this codebase has twice been taken down by adding heavy
native packages to the shared conda env, so "no new deps" is worth real effort.

DESIGN RULES APPLIED (and why)
------------------------------
* ONE hue for every bar, never a darker-where-bigger ramp. Ligands and residues
  are nominal categories — their order comes FROM the value being plotted, so
  shading by magnitude would encode bar length twice and burn the only free
  channel on information the length already carries.
* Horizontal bars, because compound names are long and unwrappable.
* Bars capped at 22px with the band's remainder left as air; 4px rounded data
  end, square at the baseline; hairline solid gridlines one step off the
  surface. The data is the only thing allowed to be loud.
* Values sit at the bar tip in ink, never in the series color — a coloured hue
  that works as a fill is not legible as text.
* No legend: a single series is already named by the title, so a one-swatch box
  would only restate it.
* Surface is white to match the document page the figure lands on; the palette
  was validated against that surface, not the default off-white.

A one-bar bar chart is not a chart, so the affinity figure is skipped when there
is only one ligand — the summary table already states that number.
"""

from collections import Counter

# ── palette (validated against a #ffffff surface) ──────────────────────────
SERIES = "#2a78d6"      # categorical slot 1, the single hue for every bar
# Ordinal ramp for the contact map: one hue, light→dark. On a light surface an
# ordinal step must still clear 2:1 against it, so the pale step is 250 — not
# the near-white end of the ramp, which is only legal for continuous scales.
SEQ_LIGHT = "#86b6ef"   # blue step 250 — "contact"
SEQ_STRONG = "#2a78d6"  # blue step 450 — "hydrogen bond"
NEUTRAL = "#f0efec"     # "no contact": present as a cell, recedes as a value
SURFACE = "#ffffff"     # the docx page
INK = "#0b0b0b"         # primary text
INK_SECOND = "#52514e"  # subtitles
INK_MUTED = "#898781"   # axis + category labels
GRID = "#e1e0d9"        # hairline gridline
AXIS = "#c3c2b7"        # baseline

FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, '
        'Roboto, Helvetica, Arial, sans-serif')

BAR_H = 22        # ≤24px cap
BAND_H = 32       # leftover (10px) is deliberate air, and exceeds the 2px gap
PAD_L = 268       # MAX gutter for category labels (see _gutter)
PAD_L_MIN = 92    # MIN gutter, so short labels don't strand an empty band
PAD_R = 96        # room for the value at each bar tip (+ any H-bond annotation)
PAD_T = 68        # title + subtitle
PAD_B = 58        # axis labels, then the caption clear of them
MARGIN = 28       # left margin for title / subtitle / caption
CHAR_W = 6.05     # ≈ average advance of 11.5px sans, for truncation only


def _gutter(labels):
    """Width of the category-label column, sized to the labels actually present.

    Fixing this at the width long compound names need would strand a wide empty
    band beside short ones (residue codes are ~6 characters), which reads as a
    layout mistake. Clamped at both ends: never so narrow that labels crowd the
    baseline, never so wide that it eats the plot.
    """
    longest = max((len(str(x)) for x in labels), default=0)
    return int(max(PAD_L_MIN, min(PAD_L, longest * CHAR_W + 24)))


def _esc(s):
    """XML-escape. Compound names really do contain & and < (e.g. '<0.1')."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _truncate(text, max_px):
    """Shorten to fit a pixel width, with an ellipsis.

    SVG has no text metrics available at build time, so this estimates from an
    average advance. It errs short — a slightly early ellipsis is fine, a label
    overflowing into the plot is not.
    """
    s = str(text)
    limit = max(4, int(max_px / CHAR_W))
    return s if len(s) <= limit else s[:limit - 1].rstrip(" ,-") + "…"


def _nice_ticks(vmax, target=5):
    """Round axis ticks to clean numbers (0 / 2 / 4 …) covering vmax.

    Ticks carry every value that isn't directly labelled, so they have to land
    on numbers a reader can hold in their head, not on the raw data maximum.
    """
    import math
    if vmax <= 0:
        return [0], 1.0
    raw = vmax / max(1, target)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = 10 * mag
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    top = math.ceil(vmax / step) * step
    n = int(round(top / step))
    return [i * step for i in range(n + 1)], top


def _bar_path(x0, y, w, h, r=4):
    """A bar with a rounded DATA end and a square baseline end.

    Rounding only the growing end is what keeps a row of bars reading as
    measurements from a common baseline rather than as floating pills.
    """
    r = max(0.0, min(float(r), float(w)))
    if w <= 0.5:
        return ""
    if r <= 0.5:
        return f"M{x0:.1f},{y:.1f} h{w:.1f} v{h:.1f} h-{w:.1f} Z"
    return (f"M{x0:.1f},{y:.1f} "
            f"H{x0 + w - r:.1f} "
            f"A{r:.1f},{r:.1f} 0 0 1 {x0 + w:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} "
            f"A{r:.1f},{r:.1f} 0 0 1 {x0 + w - r:.1f},{y + h:.1f} "
            f"H{x0:.1f} Z")


def _frame(width, height, title, subtitle):
    """Opening SVG + title block, shared by both figures.

    Title, subtitle and caption all hang off the same left margin rather than
    off the plot edge, so the text block stays aligned as the gutter flexes.
    """
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family=\'{FONT}\'>',
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
        f'<text x="{MARGIN}" y="30" font-size="17" font-weight="600" '
        f'fill="{INK}">{_esc(title)}</text>',
        f'<text x="{MARGIN}" y="50" font-size="12.5" '
        f'fill="{INK_SECOND}">{_esc(subtitle)}</text>',
    ]


def _axis(out, x0, plot_w, y_top, y_bot, ticks, top, unit="", negate=False):
    """Hairline vertical gridlines + tick labels, drawn UNDER the bars.

    `negate` labels the scale as it truly runs for docking scores — 0, -2, -4 …
    — while the bars still grow rightward by magnitude. Vina affinities are
    negative and more-negative is tighter binding, so this is the axis a reader
    of a docking paper expects; without it the scale silently reports
    magnitudes that are the opposite sign to every number in the table.
    """
    for t in ticks:
        x = x0 + (t / top) * plot_w if top else x0
        out.append(f'<line x1="{x:.1f}" y1="{y_top}" x2="{x:.1f}" y2="{y_bot}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        lab = ("0" if (negate and t == 0) else
               (f"−{t:g}{unit}" if negate else f"{t:g}{unit}"))
        out.append(f'<text x="{x:.1f}" y="{y_bot + 18}" font-size="11" '
                   f'fill="{INK_MUTED}" text-anchor="middle">{lab}</text>')
    out.append(f'<line x1="{x0}" y1="{y_top}" x2="{x0}" y2="{y_bot}" '
               f'stroke="{AXIS}" stroke-width="1"/>')


def affinity_chart_svg(rows, width=900):
    """Binding affinity per ligand, strongest first.

    Vina affinities are negative and more-negative means tighter binding, which
    inverts the usual "longer bar = more" intuition. The bars are drawn from
    magnitude so length still reads as strength, while every label keeps its
    real signed value and the subtitle states the convention outright.

    Returns an SVG string, or None when there is nothing worth plotting.
    """
    pairs = []
    for r in rows or []:
        try:
            v = float(r.get("Best affinity (kcal/mol)"))
        except (TypeError, ValueError):
            continue            # "FAILED" and blanks simply aren't plottable
        if v < 0:
            pairs.append((str(r.get("Ligand", "?")), v))
    if len(pairs) < 2:
        return None             # one bar is not a chart — the table says it

    pairs.sort(key=lambda p: p[1])          # most negative (strongest) first
    mags = [abs(v) for _, v in pairs]
    ticks, top = _nice_ticks(max(mags))

    pad_l = _gutter([_truncate(lbl, PAD_L - 24) for lbl, _ in pairs])
    plot_w = width - pad_l - PAD_R
    height = PAD_T + len(pairs) * BAND_H + PAD_B
    y_top, y_bot = PAD_T, PAD_T + len(pairs) * BAND_H

    out = _frame(width, height,
                 "Binding affinity by ligand",
                 "More negative = stronger predicted binding (AutoDock Vina, kcal/mol)")
    _axis(out, pad_l, plot_w, y_top, y_bot, ticks, top, negate=True)

    for i, (label, v) in enumerate(pairs):
        y = y_top + i * BAND_H + (BAND_H - BAR_H) / 2
        w = (abs(v) / top) * plot_w if top else 0
        out.append(f'<path d="{_bar_path(pad_l, y, w, BAR_H)}" fill="{SERIES}"/>')
        out.append(f'<text x="{pad_l - 10}" y="{y + BAR_H / 2 + 4:.1f}" '
                   f'font-size="11.5" fill="{INK_MUTED}" text-anchor="end">'
                   f'{_esc(_truncate(label, pad_l - 22))}</text>')
        out.append(f'<text x="{pad_l + w + 8:.1f}" y="{y + BAR_H / 2 + 4:.1f}" '
                   f'font-size="11.5" font-weight="600" fill="{INK}">'
                   f'−{abs(v):.1f}</text>')

    out.append(f'<text x="{MARGIN}" y="{height - 12}" font-size="11" '
               f'fill="{INK_MUTED}">Longer bar = more negative ΔG = tighter '
               f'predicted binding.</text>')
    out.append("</svg>")
    return "\n".join(out)


def contact_heatmap_svg(rows, width=960, top_n=14):
    """Ligand × residue contact matrix — which ligands touch which residues.

    This is the figure a multi-ligand docking study is actually about: the two
    bar charts each collapse one axis (per-ligand strength, per-residue
    popularity), and only the matrix shows the PATTERN — whether the ligands
    share a binding mode or split into groups that engage different parts of
    the pocket. It is genuinely two-dimensional data, which is why it earns a
    grid where a 3-D bar would only be adding a decorative axis to a single
    number per ligand.

    Cells are an ORDINAL scale of contact specificity, one hue, light→dark:
    no contact → contact → hydrogen bond. Absent cells keep a neutral wash
    rather than nothing so the grid still reads as a matrix, and every step is
    named in a scale legend, since here colour carries meaning on its own.

    Rows are ordered by affinity and columns by contact frequency, matching the
    two bar charts, so a reader moving between figures keeps their bearings.

    Returns an SVG string, or None when the data can't support a matrix.
    """
    def _split(v):
        return [x.strip() for x in str(v or "").split(";") if x.strip() and x.strip() != "-"]

    ligands, contacts = [], Counter()
    for r in rows or []:
        res = set(_split(r.get("All interacting residues")))
        if not res:
            continue
        try:
            aff = float(r.get("Best affinity (kcal/mol)"))
        except (TypeError, ValueError):
            aff = 0.0
        ligands.append({"label": str(r.get("Ligand", "?")), "aff": aff, "res": res,
                        "hb": set(_split(r.get("H-bond residues")))})
        for x in res:
            contacts[x] += 1
    if len(ligands) < 2 or len(contacts) < 2:
        return None

    ligands.sort(key=lambda d: d["aff"])                       # strongest first
    cols = [r for r, _ in sorted(contacts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]

    # Cells widen when there are few residues, so a 5-column map fills its
    # figure instead of huddling against the labels; capped so a 2-column map
    # doesn't turn into slabs. The figure is then sized to its content rather
    # than padded out to a fixed width, which is what left it looking lopsided.
    CELL_H, GAP = 26, 2
    CELL_W = int(max(38, min(64, 430 / max(1, len(cols)))))
    COL_LABEL_H = 56
    pad_l = _gutter([_truncate(l["label"], PAD_L - 24) for l in ligands])
    grid_w = len(cols) * CELL_W
    width = max(pad_l + grid_w + MARGIN + 24, 680)
    y_top = PAD_T + COL_LABEL_H
    grid_h = len(ligands) * CELL_H
    height = y_top + grid_h + 74                               # + legend + caption

    out = _frame(width, height,
                 "Ligand × residue contact map",
                 f"Which of the {len(ligands)} ligands contact which binding-site "
                 f"residues, and where those contacts are hydrogen bonds")

    # column headers, rotated so 7-character residue codes don't collide
    for j, res in enumerate(cols):
        cx = pad_l + j * CELL_W + CELL_W / 2
        out.append(f'<text x="{cx:.1f}" y="{y_top - 8}" font-size="11" '
                   f'fill="{INK_MUTED}" text-anchor="start" '
                   f'transform="rotate(-45 {cx:.1f} {y_top - 8})">{_esc(res)}</text>')

    for i, lig in enumerate(ligands):
        y = y_top + i * CELL_H
        out.append(f'<text x="{pad_l - 10}" y="{y + CELL_H / 2 + 4:.1f}" '
                   f'font-size="11.5" fill="{INK_MUTED}" text-anchor="end">'
                   f'{_esc(_truncate(lig["label"], pad_l - 22))}</text>')
        for j, res in enumerate(cols):
            x = pad_l + j * CELL_W
            if res in lig["hb"]:
                fill = SEQ_STRONG
            elif res in lig["res"]:
                fill = SEQ_LIGHT
            else:
                fill = NEUTRAL
            # the 2px inset IS the separator — never a stroke around a mark
            out.append(f'<rect x="{x + GAP / 2:.1f}" y="{y + GAP / 2:.1f}" '
                       f'width="{CELL_W - GAP}" height="{CELL_H - GAP}" '
                       f'rx="2" fill="{fill}"/>')

    # scale legend — colour carries meaning here, so it is never colour-alone
    ly = y_top + grid_h + 26
    lx = MARGIN
    for fill, name in ((NEUTRAL, "no contact"), (SEQ_LIGHT, "contact"),
                       (SEQ_STRONG, "hydrogen bond")):
        out.append(f'<rect x="{lx}" y="{ly - 9}" width="12" height="12" rx="2" fill="{fill}"/>')
        out.append(f'<text x="{lx + 18}" y="{ly + 1}" font-size="11" '
                   f'fill="{INK_SECOND}">{name}</text>')
        lx += 20 + len(name) * CHAR_W + 22

    out.append(f'<text x="{MARGIN}" y="{height - 12}" font-size="11" '
               f'fill="{INK_MUTED}">Rows ordered by affinity (strongest first); '
               f'columns by how many ligands contact the residue.</text>')
    out.append("</svg>")
    return "\n".join(out)


def residue_frequency_svg(rows, width=900, top_n=14):
    """How many ligands contact each binding-site residue.

    A residue touched by most of the series is the pocket's real anchor point,
    which is exactly what a reader wants from a multi-ligand run and what a
    per-ligand table buries. H-bond counts are tallied separately so the
    subtitle can say how many of the contacts are hydrogen bonds.

    Returns an SVG string, or None when there is nothing worth plotting.
    """
    def _split(v):
        return [x.strip() for x in str(v or "").split(";") if x.strip() and x.strip() != "-"]

    contacts, hbond = Counter(), Counter()
    n_lig = 0
    for r in rows or []:
        res = _split(r.get("All interacting residues"))
        if not res:
            continue
        n_lig += 1
        for x in set(res):                  # per LIGAND, not per contact
            contacts[x] += 1
        for x in set(_split(r.get("H-bond residues"))):
            hbond[x] += 1
    if len(contacts) < 2:
        return None

    ranked = sorted(contacts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ticks, top = _nice_ticks(max(c for _, c in ranked))

    pad_l = _gutter([r for r, _ in ranked])
    plot_w = width - pad_l - PAD_R
    height = PAD_T + len(ranked) * BAND_H + PAD_B
    y_top, y_bot = PAD_T, PAD_T + len(ranked) * BAND_H

    shown = f"top {len(ranked)} of {len(contacts)}" if len(contacts) > len(ranked) \
        else f"all {len(contacts)}"
    out = _frame(width, height,
                 "Binding-site residue contact frequency",
                 f"How many of the {n_lig} docked ligands contact each residue "
                 f"({shown} residues)")
    _axis(out, pad_l, plot_w, y_top, y_bot, ticks, top)

    for i, (res, n) in enumerate(ranked):
        y = y_top + i * BAND_H + (BAND_H - BAR_H) / 2
        w = (n / top) * plot_w if top else 0
        out.append(f'<path d="{_bar_path(pad_l, y, w, BAR_H)}" fill="{SERIES}"/>')
        out.append(f'<text x="{pad_l - 10}" y="{y + BAR_H / 2 + 4:.1f}" '
                   f'font-size="11.5" fill="{INK_MUTED}" text-anchor="end">'
                   f'{_esc(_truncate(res, pad_l - 22))}</text>')
        hb = hbond.get(res, 0)
        tip = f"{n}" + (f"  ({hb} H-bond)" if hb else "")
        out.append(f'<text x="{pad_l + w + 8:.1f}" y="{y + BAR_H / 2 + 4:.1f}" '
                   f'font-size="11.5" font-weight="600" fill="{INK}">{_esc(tip)}</text>')

    out.append(f'<text x="{MARGIN}" y="{height - 12}" font-size="11" '
               f'fill="{INK_MUTED}">A residue contacted by many ligands is a '
               f'likely anchor point of the pocket.</text>')
    out.append("</svg>")
    return "\n".join(out)
