"""
MUMO — figures for the STRING report.

Hand-written SVG, same reasoning as charts.py and ramachandran.py: the .docx
export already rasterises SVG through headless Chromium, so these need no
plotting library and therefore no new dependency.

Every figure takes a `dark` flag because the same drawing is used twice — dark
in the app panel, light in the exported report — and a chart that only reads
on one background is a chart that gets screenshotted badly into the other.
"""

_FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, Roboto, "
         "Helvetica, Arial, sans-serif")


def _palette(dark):
    if dark:
        return {"bg": "none", "ink": "#eef5fa", "ink2": "#cdd8df",
                "muted": "#93a0aa", "grid": "rgba(255,255,255,0.10)",
                "axis": "rgba(255,255,255,0.22)", "accent": "#6fb8ec"}
    return {"bg": "#ffffff", "ink": "#0b0b0b", "ink2": "#52514e",
            "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
            "accent": "#2a78d6"}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _ramp(v, dark):
    """0..1 -> interpolated fill. Sequential single-hue, so the eye reads it as
    a magnitude rather than as categories."""
    v = max(0.0, min(1.0, float(v)))
    if dark:
        r0, g0, b0 = 12, 26, 36            # near-background
        r1, g1, b1 = 111, 184, 236         # accent
    else:
        r0, g0, b0 = 244, 248, 252
        r1, g1, b1 = 26, 92, 158
    f = v ** 0.75                          # lift the low end so weak evidence shows
    return f"rgb({int(r0+(r1-r0)*f)},{int(g0+(g1-g0)*f)},{int(b0+(b1-b0)*f)})"


def heatmap_svg(matrix, title="Evidence by channel", dark=True, width=680):
    """Partners x STRING evidence channels.

    The combined score hides WHY a link exists — this is the figure that shows
    an interaction resting entirely on text mining rather than experiment.
    """
    rows, cols, vals = matrix.get("rows") or [], matrix.get("cols") or [], matrix.get("values") or []
    if not rows or not cols:
        return ""
    P = _palette(dark)
    # TOP has to clear the rotated column labels, not just the subtitle: at -38
    # degrees a 13-character label like "Co-expression" reaches ~40px upward,
    # and at 74 they were being cut off by the top of the canvas.
    LEFT, TOP, RIGHT, BOT = 132, 112, 16, 54
    cw = max(46, (width - LEFT - RIGHT) // len(cols))
    ch = 22
    w = LEFT + cw * len(cols) + RIGHT
    h = TOP + ch * len(rows) + BOT

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
         f'viewBox="0 0 {w} {h}" font-family="{_FONT}">']
    if P["bg"] != "none":
        o.append(f'<rect width="{w}" height="{h}" fill="{P["bg"]}"/>')
    o.append(f'<text x="14" y="24" font-size="14" font-weight="600" '
             f'fill="{P["ink"]}">{_esc(title)}</text>')
    o.append(f'<text x="14" y="42" font-size="11" fill="{P["muted"]}">'
             f'Darker = stronger evidence in that channel (0 to 1)</text>')

    for c, label in enumerate(cols):
        x = LEFT + c * cw + cw / 2
        o.append(f'<text x="{x:.1f}" y="{TOP - 8}" font-size="10" '
                 f'fill="{P["ink2"]}" text-anchor="end" '
                 f'transform="rotate(-38 {x:.1f} {TOP - 8})">{_esc(label)}</text>')

    for r, name in enumerate(rows):
        y = TOP + r * ch
        o.append(f'<text x="{LEFT - 8}" y="{y + ch/2 + 3.5:.1f}" font-size="11" '
                 f'fill="{P["ink"]}" text-anchor="end">{_esc(name)}</text>')
        for c in range(len(cols)):
            v = vals[r][c] if r < len(vals) and c < len(vals[r]) else 0.0
            x = LEFT + c * cw
            o.append(f'<rect x="{x}" y="{y}" width="{cw - 2}" height="{ch - 2}" '
                     f'rx="2" fill="{_ramp(v, dark)}"/>')
            if v >= 0.4:
                o.append(f'<text x="{x + (cw-2)/2:.1f}" y="{y + ch/2 + 3.5:.1f}" '
                         f'font-size="9.5" text-anchor="middle" '
                         f'fill="{"#08131b" if v > 0.72 else P["ink"]}">'
                         f'{v:.2f}</text>')

    o.append(f'<text x="14" y="{h - 18}" font-size="10" fill="{P["muted"]}">'
             f'Experiments and Databases are direct evidence; Text mining only '
             f'means two proteins are discussed together.</text>')
    o.append("</svg>")
    return "\n".join(o)


def tree_svg(tree, title="Sequence similarity", dark=True, width=680):
    """Rectangular dendrogram of a UPGMA tree.

    Leaves are drawn at a common right edge (the tree is ultrametric), so
    horizontal position of each join reads directly as distance.
    """
    if not tree:
        return ""
    P = _palette(dark)

    leaves = []

    def collect(n):
        if "name" in n:
            leaves.append(n)
        else:
            for c in n["children"]:
                collect(c)
    collect(tree)
    if len(leaves) < 2:
        return ""

    LEFT, TOP, RIGHT, BOT = 18, 66, 128, 46
    row = 22
    h = TOP + row * len(leaves) + BOT
    span = width - LEFT - RIGHT
    root_h = max(1e-9, tree.get("height", 1.0))

    ypos = {id(l): TOP + i * row + row / 2 for i, l in enumerate(leaves)}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
         f'viewBox="0 0 {width} {h}" font-family="{_FONT}">']
    if P["bg"] != "none":
        o.append(f'<rect width="{width}" height="{h}" fill="{P["bg"]}"/>')
    o.append(f'<text x="14" y="24" font-size="14" font-weight="600" '
             f'fill="{P["ink"]}">{_esc(title)}</text>')
    o.append(f'<text x="14" y="42" font-size="11" fill="{P["muted"]}">'
             f'k-mer distance, average linkage — sequence family structure, '
             f'not an aligned phylogeny</text>')

    def x_of(height):
        return LEFT + span * (1.0 - height / root_h)

    def draw(n):
        if "name" in n:
            y = ypos[id(n)]
            o.append(f'<text x="{LEFT + span + 8}" y="{y + 3.5:.1f}" font-size="11" '
                     f'fill="{P["ink"]}">{_esc(n["name"])}</text>')
            return y
        ys = [draw(c) for c in n["children"]]
        y0, y1 = min(ys), max(ys)
        x = x_of(n.get("height", 0.0))
        o.append(f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" y2="{y1:.1f}" '
                 f'stroke="{P["accent"]}" stroke-width="1.5"/>')
        for c, y in zip(n["children"], ys):
            cx = x_of(c.get("height", 0.0)) if "children" in c else LEFT + span
            o.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{y:.1f}" '
                     f'stroke="{P["accent"]}" stroke-width="1.5"/>')
        return (y0 + y1) / 2

    draw(tree)
    o.append(f'<line x1="{LEFT}" y1="{h - BOT + 10}" x2="{LEFT + span}" '
             f'y2="{h - BOT + 10}" stroke="{P["axis"]}" stroke-width="1"/>')
    for frac in (0.0, 0.5, 1.0):
        x = LEFT + span * frac
        o.append(f'<text x="{x:.1f}" y="{h - BOT + 24}" font-size="9.5" '
                 f'fill="{P["muted"]}" text-anchor="middle">'
                 f'{root_h * (1 - frac):.2f}</text>')
    o.append(f'<text x="{LEFT + span/2:.1f}" y="{h - 10}" font-size="10" '
             f'fill="{P["muted"]}" text-anchor="middle">distance '
             f'(0 = identical sequence)</text>')
    o.append("</svg>")
    return "\n".join(o)


def enrichment_svg(rows, title="Functional enrichment", dark=True, width=680, top=12):
    """Horizontal bars of the most enriched terms, by false discovery rate.

    Bars are -log10(FDR) because raw p-values span orders of magnitude and a
    linear axis would render everything except the top hit as a stub.
    """
    import math
    if not rows:
        return ""
    P = _palette(dark)
    items = []
    for r in rows[:top]:
        try:
            fdr = float(r.get("fdr") or r.get("p_value") or 1.0)
        except (TypeError, ValueError):
            fdr = 1.0
        fdr = max(fdr, 1e-300)
        items.append({
            "term": r.get("description") or r.get("term") or "?",
            "score": -math.log10(fdr),
            "n": r.get("number_of_genes") or r.get("n") or "",
            "cat": r.get("category") or "",
        })
    if not items:
        return ""
    LEFT, TOP, RIGHT, BOT = 250, 62, 44, 34
    bh, gap = 20, 7
    h = TOP + (bh + gap) * len(items) + BOT
    span = width - LEFT - RIGHT
    top_score = max(i["score"] for i in items) or 1.0

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
         f'viewBox="0 0 {width} {h}" font-family="{_FONT}">']
    if P["bg"] != "none":
        o.append(f'<rect width="{width}" height="{h}" fill="{P["bg"]}"/>')
    o.append(f'<text x="14" y="24" font-size="14" font-weight="600" '
             f'fill="{P["ink"]}">{_esc(title)}</text>')
    o.append(f'<text x="14" y="42" font-size="11" fill="{P["muted"]}">'
             f'Longer bar = less likely by chance (-log10 FDR)</text>')

    for i, it in enumerate(items):
        y = TOP + i * (bh + gap)
        term = it["term"]
        if len(term) > 40:
            term = term[:38] + "…"
        o.append(f'<text x="{LEFT - 10}" y="{y + bh/2 + 4:.1f}" font-size="11" '
                 f'fill="{P["ink"]}" text-anchor="end">{_esc(term)}</text>')
        bw = max(2.0, span * (it["score"] / top_score))
        o.append(f'<rect x="{LEFT}" y="{y}" width="{bw:.1f}" height="{bh}" rx="3" '
                 f'fill="{_ramp(0.35 + 0.65 * it["score"] / top_score, dark)}"/>')
        o.append(f'<text x="{LEFT + bw + 7:.1f}" y="{y + bh/2 + 4:.1f}" '
                 f'font-size="10" fill="{P["muted"]}">{it["score"]:.1f}</text>')
    o.append("</svg>")
    return "\n".join(o)


def orbital_svg(qm, title="Frontier molecular orbitals", dark=True, width=560):
    """Orbital energy-level diagram: occupied levels, the gap, and the frontier.

    A ladder rather than a bar chart, because orbital energies ARE levels — the
    vertical axis is energy and the eye should read the HOMO-LUMO separation
    directly as the distance between two rungs.
    """
    if not qm or qm.get("_error") or "homo_ev" not in qm:
        return ""
    P = _palette(dark)
    levels = qm.get("levels") or []
    homo, lumo = qm["homo_ev"], qm["lumo_ev"]

    # Show a window around the frontier: the deep core levels are far away and
    # would compress the interesting region into a single line.
    span = max(2.5, (lumo - homo) * 2.6)
    lo, hi = homo - span, lumo + span
    shown = [l for l in levels if lo <= l["energy_ev"] <= hi] or [
        {"energy_ev": homo, "occupation": 2.0, "label": "HOMO"},
        {"energy_ev": lumo, "occupation": 0.0, "label": "LUMO"}]

    LEFT, TOP, RIGHT, BOT = 96, 62, 150, 56
    h = 330
    plot_h = h - TOP - BOT
    x0, x1 = LEFT, width - RIGHT

    def y(e):
        return TOP + plot_h * (hi - e) / (hi - lo)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
         f'viewBox="0 0 {width} {h}" font-family="{_FONT}">']
    if P["bg"] != "none":
        o.append(f'<rect width="{width}" height="{h}" fill="{P["bg"]}"/>')
    o.append(f'<text x="14" y="24" font-size="14" font-weight="600" '
             f'fill="{P["ink"]}">{_esc(title)}</text>')
    o.append(f'<text x="14" y="42" font-size="11" fill="{P["muted"]}">'
             f'{_esc(qm.get("method", "GFN2-xTB"))} · energies in eV</text>')

    # energy axis
    o.append(f'<line x1="{LEFT-30}" y1="{TOP}" x2="{LEFT-30}" y2="{TOP+plot_h}" '
             f'stroke="{P["axis"]}" stroke-width="1"/>')
    for frac in (0, 0.5, 1):
        e = hi - (hi - lo) * frac
        yy = y(e)
        o.append(f'<text x="{LEFT-36}" y="{yy+3.5:.1f}" font-size="9.5" '
                 f'fill="{P["muted"]}" text-anchor="end">{e:.1f}</text>')

    # the gap, drawn as the thing the eye should land on
    o.append(f'<rect x="{x0}" y="{y(lumo):.1f}" width="{x1-x0}" '
             f'height="{y(homo)-y(lumo):.1f}" fill="{_ramp(0.18, dark)}" opacity="0.55"/>')
    mid = (y(homo) + y(lumo)) / 2
    o.append(f'<text x="{(x0+x1)/2:.1f}" y="{mid+4:.1f}" font-size="12" '
             f'font-weight="600" fill="{P["ink"]}" text-anchor="middle">'
             f'gap {qm["gap_ev"]:.2f} eV</text>')

    for lv in shown:
        e = lv["energy_ev"]
        occupied = (lv.get("occupation") or 0) > 0
        lab = lv.get("label") or ""
        stroke = P["accent"] if lab in ("HOMO", "LUMO") else P["axis"]
        wdt = 2.2 if lab in ("HOMO", "LUMO") else 1.1
        o.append(f'<line x1="{x0}" y1="{y(e):.1f}" x2="{x1}" y2="{y(e):.1f}" '
                 f'stroke="{stroke}" stroke-width="{wdt}" '
                 f'{"" if occupied else "stroke-dasharray=\'5 4\'"}/>')
        if lab:
            o.append(f'<text x="{x1+8}" y="{y(e)+4:.1f}" font-size="11" '
                     f'font-weight="600" fill="{P["ink"]}">{lab} {e:.2f}</text>')

    o.append(f'<text x="14" y="{h-16}" font-size="10" fill="{P["muted"]}">'
             f'Solid = occupied, dashed = empty. A smaller gap means the molecule '
             f'engages more readily in electron transfer.</text>')
    o.append("</svg>")
    return "\n".join(o)


def orbital_png(qm, title="Frontier molecular orbitals", dark=False, width=640, height=400):
    """The same orbital energy-level diagram as orbital_svg, but rendered
    straight to PNG bytes with matplotlib instead of SVG + headless Chromium.

    Every other chart in MUMO is a rich interactive scene (a 3D pose, a network
    graph) that genuinely needs a browser to rasterize. This one is a handful
    of horizontal lines and text labels — using a full Chromium launch for it
    was the wrong tool for the job, and in production it has twice come back
    with no image at all (once in the docking .docx, once in the live HOMO/LUMO
    panel) while the browser-based charts around it rendered fine. Rather than
    keep guessing at a container-specific Playwright failure with no server-log
    access, this removes the dependency for the one diagram users ask for by
    name: matplotlib's Agg backend needs no display, no subprocess, and no
    browser binary, so it cannot fail for that class of reason.

    Returns PNG bytes, or None if qm has no usable orbital data.
    """
    if not qm or qm.get("_error") or "homo_ev" not in qm:
        return None
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink = "#e8e6e1" if dark else "#0b0b0b"
    muted = "#a6a49c" if dark else "#6b6960"
    bg = "#14140f" if dark else "#ffffff"
    axis_c = "#4a483f" if dark else "#c9c7bd"
    accent = "#5fd0a0" if dark else "#1f9d63"

    homo, lumo, gap = qm["homo_ev"], qm["lumo_ev"], qm["gap_ev"]
    levels = qm.get("levels") or []
    span = max(2.5, (lumo - homo) * 2.6)
    lo, hi = homo - span, lumo + span
    shown = [lv for lv in levels if lo <= lv["energy_ev"] <= hi] or [
        {"energy_ev": homo, "occupation": 2.0, "label": "HOMO"},
        {"energy_ev": lumo, "occupation": 0.0, "label": "LUMO"}]

    dpi = 110
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    fig.subplots_adjust(top=0.78, bottom=0.16, left=0.14, right=0.96)

    xlo, xhi = 0.14, 0.72   # axes-fraction span of the ladder itself
    ax.axhspan(min(homo, lumo), max(homo, lumo), xmin=xlo, xmax=xhi,
               facecolor=accent, alpha=0.16, edgecolor="none", zorder=1)
    ax.text((xlo + xhi) / 2, (homo + lumo) / 2, f"gap {gap:.2f} eV",
            transform=ax.get_yaxis_transform(), ha="center", va="center",
            fontsize=10, fontweight="bold", color=ink, zorder=3)

    for lv in shown:
        e = lv["energy_ev"]
        occupied = (lv.get("occupation") or 0) > 0
        lab = lv.get("label") or ""
        frontier = lab in ("HOMO", "LUMO")
        ax.hlines(e, xlo, xhi, transform=ax.get_yaxis_transform(),
                  colors=accent if frontier else axis_c,
                  linewidth=2.2 if frontier else 1.1,
                  linestyles="solid" if occupied else "dashed", zorder=2)
        if lab:
            ax.text(xhi + 0.03, e, f"{lab} {e:.2f}",
                    transform=ax.get_yaxis_transform(), ha="left", va="center",
                    fontsize=9.5, fontweight="bold", color=ink)

    ax.set_ylim(lo, hi)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_ylabel("Energy (eV)", color=muted, fontsize=9.5)
    ax.tick_params(axis="y", colors=muted, labelsize=9)
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(axis_c)

    fig.text(0.03, 0.94, title, ha="left", va="top", fontsize=12,
             fontweight="bold", color=ink)
    fig.text(0.03, 0.87, f"{qm.get('method', 'GFN2-xTB')} · energies in eV",
             ha="left", va="top", fontsize=9, color=muted)
    fig.text(0.03, 0.045,
             "Solid = occupied, dashed = empty. Smaller gap = more readily\n"
             "engages in electron transfer.",
             ha="left", va="bottom", fontsize=8, color=muted, linespacing=1.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg)
    plt.close(fig)
    return buf.getvalue()
