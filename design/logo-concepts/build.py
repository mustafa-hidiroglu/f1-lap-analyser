#!/usr/bin/env python3
"""Generate the F1 Lap Analyser logo-concept SVGs (proposals only; the app icon is unchanged).

Every concept is described once as plain geometry on a 256 x 256 grid; this script writes, per concept:
  mark.svg            colour master (transparent background)
  mark-mono.svg       one colour, black
  mark-reversed.svg   one colour, white (for dark backgrounds; transparent)
  mark-on-dark.svg    colour version for dark backgrounds
  mark-small.svg      16-32 px cut (only where the master needs one)
  app-icon.svg        macOS app icon: mark on a continuous-curvature squircle tile (Big Sur grid)
  app-icon-mono.svg   app icon in one colour (graphite tile, white mark)
  preview.svg         contact sheet: colour / mono / reversed / app icon / true 64-32-16 px sizes
Run:  python3 design/logo-concepts/build.py   (then render previews with the logo-design skill's render_png.py)
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

RED = "#E8352B"        # "Apex red": warmer and softer than a flag red, still unmistakably racing
GRAPHITE = "#1D1D1F"
SILVER = "#A1A1A6"
PAPER = "#F5F5F7"
INK = "#0B0B0D"


def f(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---------------------------------------------------------------- squircle (macOS continuous corners)
def squircle_path(cx, cy, size, radius_ratio=0.225, smooth=1.32, k=0.64):
    """Apple-style continuous-corner square ("squircle"): flat sides, and each corner is one cubic whose
    curvature ramps up gradually. The corner starts `smooth` x R before the corner point (R = radius_ratio x
    size), with handles reaching `k` of the way to the corner. Equivalent to a macOS Big Sur tile."""
    h = size / 2
    R = size * radius_ratio
    L = R * smooth
    c = L * k
    x0, y0, x1, y1 = cx - h, cy - h, cx + h, cy + h
    d = f"M{f(x0 + L)} {f(y0)}H{f(x1 - L)}"
    d += f"C{f(x1 - L + c)} {f(y0)} {f(x1)} {f(y0 + L - c)} {f(x1)} {f(y0 + L)}V{f(y1 - L)}"
    d += f"C{f(x1)} {f(y1 - L + c)} {f(x1 - L + c)} {f(y1)} {f(x1 - L)} {f(y1)}H{f(x0 + L)}"
    d += f"C{f(x0 + L - c)} {f(y1)} {f(x0)} {f(y1 - L + c)} {f(x0)} {f(y1 - L)}V{f(y0 + L)}"
    d += f"C{f(x0)} {f(y0 + L - c)} {f(x0 + L - c)} {f(y0)} {f(x0 + L)} {f(y0)}Z"
    return d


# ---------------------------------------------------------------- rounded polygons (fillets)
def rounded_polygon(pts, radii):
    """Closed polygon with a circular fillet of radius radii[i] at vertex i (path data, arcs)."""
    n = len(pts)
    segs = []
    for i in range(n):
        p_prev, p, p_next = pts[i - 1], pts[i], pts[(i + 1) % n]
        v1 = (p_prev[0] - p[0], p_prev[1] - p[1])
        v2 = (p_next[0] - p[0], p_next[1] - p[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        u1, u2 = (v1[0] / l1, v1[1] / l1), (v2[0] / l2, v2[1] / l2)
        ang = math.acos(max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1])))
        d = radii[i] / math.tan(ang / 2)
        a = (p[0] + u1[0] * d, p[1] + u1[1] * d)
        b = (p[0] + u2[0] * d, p[1] + u2[1] * d)
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        sweep = 1 if cross < 0 else 0
        segs.append((a, b, radii[i], sweep))
    d = f"M{f(segs[0][0][0])} {f(segs[0][0][1])}"
    for i, (a, b, r, sw) in enumerate(segs):
        if i > 0:
            d += f"L{f(a[0])} {f(a[1])}"
        d += f"A{f(r)} {f(r)} 0 0 {sw} {f(b[0])} {f(b[1])}"
    return d + "Z"


def offset_triangle(pts, insets):
    """Inset each edge i (pts[i] -> pts[i+1]) inward by insets[i]; return the new triangle's vertices."""
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    lines = []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        nx, ny = -dy / L, dx / L
        if (cx - p[0]) * nx + (cy - p[1]) * ny < 0:
            nx, ny = -nx, -ny
        lines.append(((p[0] + nx * insets[i], p[1] + ny * insets[i]), (dx, dy)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return out


# ---------------------------------------------------------------- concepts
# Each concept: list of (role, element-builder) where role is "a" (primary colour) or "b" (accent).
# Elements are SVG strings with a {fill}/{stroke} placeholder so variants can recolour them.

def ghost():
    # You (solid disc) and your ghost (a ring, the same size) one hundredth ahead. They never touch.
    r, ring = 50, 15
    disc = f'<circle cx="74" cy="128" r="{r}" fill="{{a}}"/>'
    ring_d = (f"M182 {128 - r}A{r} {r} 0 1 1 182 {128 + r}A{r} {r} 0 1 1 182 {128 - r}Z"
              f"M182 {128 - r + ring}A{r - ring} {r - ring} 0 1 0 182 {128 + r - ring}"
              f"A{r - ring} {r - ring} 0 1 0 182 {128 - r + ring}Z")
    ringel = f'<path fill="{{b}}" fill-rule="evenodd" d="{ring_d}"/>'
    return [disc, ringel]


DELTA_OUTER = [(128, 30), (234, 214), (22, 214)]  # sits 4 units high: optical centre of an apex-up triangle


def delta():
    # The time-delta glyph. Its hollow is pushed forward: the trailing side is heavy, the leading side a
    # hairline away from breaking open. The empty space is the time you have not found yet.
    outer = rounded_polygon(DELTA_OUTER, [20, 20, 20])
    # edges: 0 = top->right (leading side), 1 = right->left (base), 2 = left->top (trailing side)
    inner_pts = offset_triangle(DELTA_OUTER, [14, 26, 66])
    inner = rounded_polygon(inner_pts[::-1], [6, 6, 6])
    return [f'<path fill="{{a}}" fill-rule="evenodd" d="{outer}{inner}"/>']


def pulse():
    # A speed trace through one corner: flat out, a hard stab of braking, the long climb back.
    # It dives toward the apex (the dot) and never quite touches it - a held breath, a heartbeat.
    d = "M28 86H64C90 86 96 166 120 166C148 166 166 86 198 86H228"
    line = f'<path fill="none" stroke="{{a}}" stroke-width="20" stroke-linecap="round" stroke-linejoin="round" d="{d}"/>'
    dot = '<circle cx="122" cy="126" r="14" fill="{b}"/>'
    return [line, dot]


def flag():
    # The chequered flag, reduced to its nine squares. One square has slipped forward out of the grid:
    # the hundredth you left on track. (Read it again and it is a die showing five: precision vs. luck.)
    s, o, rx, slip = 60, 25, 6, 26
    cells = []
    for (cx, cy) in [(0, 0), (2, 0), (1, 1), (0, 2)]:
        cells.append(f'<rect x="{o + cx * s}" y="{38 + cy * s}" width="{s}" height="{s}" rx="{rx}" fill="{{a}}"/>')
    cells.append(f'<rect x="{o + 2 * s + slip}" y="{38 + 2 * s}" width="{s}" height="{s}" rx="{rx}" fill="{{b}}"/>')
    return cells


def hundredth():
    # The number the whole app exists to explain. Everything else - traces, maps, the perfect lap - is
    # just the long answer to why the last digit is a 1. Timing-screen numerals, drawn soft and round.
    sw, H, W, r, gap = 20, 104, 58, 12, 14
    top, bot = 128 - H / 2, 128 + H / 2
    x = 17
    els = []

    def zero(x0):
        return (f'<rect x="{f(x0 + sw / 2)}" y="{f(top + sw / 2)}" width="{f(W - sw)}" height="{f(H - sw)}" '
                f'rx="{f((W - sw) / 2)}" fill="none" stroke="{{a}}" stroke-width="{sw}"/>')
    els.append(zero(x))
    x += W + gap
    els.append(f'<circle cx="{f(x + r)}" cy="{f(bot - r)}" r="{r}" fill="{{a}}"/>')
    x += 2 * r + gap
    els.append(zero(x))
    x += W + gap + 2
    stem = x + sw / 2 + 18
    els.append(f'<path fill="none" stroke="{{b}}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" '
               f'd="M{f(stem - 18)} {f(top + sw / 2 + 18)}L{f(stem)} {f(top + sw / 2)}V{f(bot - sw / 2)}"/>')
    return els


def hundredth_small():
    # 16-32 px cut: drop the leading zero, heavier strokes, wider counters.
    sw, H, W, r, gap = 30, 132, 76, 17, 14
    top, bot = 128 - H / 2, 128 + H / 2
    x = 30
    els = [f'<circle cx="{f(x + r)}" cy="{f(bot - r)}" r="{r}" fill="{{a}}"/>']
    x += 2 * r + gap
    els.append(f'<rect x="{f(x + sw / 2)}" y="{f(top + sw / 2)}" width="{f(W - sw)}" height="{f(H - sw)}" '
               f'rx="{f((W - sw) / 2)}" fill="none" stroke="{{a}}" stroke-width="{sw}"/>')
    x += W + gap + 4
    stem = x + sw / 2 + 24
    els.append(f'<path fill="none" stroke="{{b}}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" '
               f'd="M{f(stem - 24)} {f(top + sw / 2 + 24)}L{f(stem)} {f(top + sw / 2)}V{f(bot - sw / 2)}"/>')
    return els


SMALL = {"05-hundredth": hundredth_small}

CONCEPTS = [
    # dir, title, builder, mark colours (a, b), tile, tile mark colours (a, b), mark scale in tile
    ("01-ghost", "Ghost", ghost, (RED, SILVER), INK, (RED, "#C7C7CC"), 0.60),
    ("02-delta", "Delta", delta, (RED, RED), RED, ("#FFFFFF", "#FFFFFF"), 0.56),
    ("03-pulse", "Pulse", pulse, (GRAPHITE, RED), PAPER, (GRAPHITE, RED), 0.62),
    ("04-slipped-square", "Slipped Square", flag, (GRAPHITE, RED), INK, ("#FFFFFF", RED), 0.54),
    ("05-hundredth", "Hundredth", hundredth, (GRAPHITE, RED), INK, ("#FFFFFF", RED), 0.66),
]

TILE_GRAD = {
    INK: ("#2A2A2D", "#0B0B0D"),
    RED: ("#F0473B", "#D42A20"),
    PAPER: ("#FFFFFF", "#E8E8ED"),
}


def body(builder, a, b):
    return "".join(e.format(a=a, b=b) for e in builder())


def svg(inner, title, vb="0 0 256 256", w=256, h=256, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w}" height="{h}" role="img">'
            f"<title>{title}</title>{defs}{inner}</svg>\n")


def app_icon(builder, tile, ca, cb, scale, title, mono=False):
    # macOS Big Sur grid on a 1024 canvas: 824 px tile, 100 px margin -> on 256: 206 tile at 25.
    sq = squircle_path(128, 128, 206)
    if mono:
        tile_el = f'<path fill="{GRAPHITE}" d="{sq}"/>'
        defs = ""
    else:
        g0, g1 = TILE_GRAD[tile]
        defs = (f'<defs><linearGradient id="t" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient></defs>')
        tile_el = f'<path fill="url(#t)" d="{sq}"/>'
    k = scale
    tx = 128 - 128 * k
    ty = 128 - 128 * k - 2  # optical centring: a hair above geometric centre
    mark = f'<g transform="translate({f(tx)} {f(ty)}) scale({k})">{body(builder, ca, cb)}</g>'
    return svg(tile_el + mark, title, defs=defs)


def preview(builder, cols, tile, tcols, scale, title, small=None):
    """Contact sheet 1200 x 640: colour, mono, reversed, app icon, mono app icon, and true 64/32/16 px."""
    a, b = cols
    ta, tb = tcols
    sq = squircle_path(128, 128, 206)
    g0, g1 = TILE_GRAD[tile]
    defs = (f'<defs><linearGradient id="t" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{g0}"/><stop offset="1" stop-color="{g1}"/></linearGradient></defs>')
    k = scale
    icon_mark = f'<g transform="translate({f(128 - 128 * k)} {f(126 - 128 * k)}) scale({k})">{body(builder, ta, tb)}</g>'
    icon = f'<path fill="url(#t)" d="{sq}"/>{icon_mark}'
    sb = small or builder
    sk = 0.62 if small else k
    icon_small = (f'<path fill="url(#t)" d="{sq}"/><g transform="translate({f(128 - 128 * sk)} {f(126 - 128 * sk)}) '
                  f'scale({sk})">{body(sb, ta, tb)}</g>')
    mono_icon = (f'<path fill="{GRAPHITE}" d="{sq}"/>'
                 f'<g transform="translate({f(128 - 128 * k)} {f(126 - 128 * k)}) scale({k})">{body(builder, "#FFFFFF", "#FFFFFF")}</g>')

    def place(content, x, y, size):
        s = size / 256
        return f'<g transform="translate({x} {y}) scale({f(s)})">{content}</g>'

    def label(x, y, t, fill="#6E6E73"):
        return (f'<text x="{x}" y="{y}" font-family="-apple-system, Helvetica Neue, Arial" font-size="15" '
                f'fill="{fill}" text-anchor="middle">{t}</text>')

    out = [f'<rect width="1200" height="640" fill="#FFFFFF"/>']
    # row 1: colour on white, mono black, reversed on ink, app icon
    out.append(place(body(builder, a, b), 40, 40, 240) + label(160, 306, "colour"))
    out.append(place(body(builder, "#000000", "#000000"), 330, 40, 240) + label(450, 306, "one colour"))
    out.append(f'<rect x="610" y="20" width="280" height="300" rx="18" fill="{INK}"/>')
    out.append(place(body(builder, "#FFFFFF", "#FFFFFF"), 630, 40, 240) + label(750, 306, "reversed", "#8E8E93"))
    out.append(place(icon, 920, 40, 240) + label(1040, 306, "macOS app icon"))
    # row 2: app icon ladder + mark ladder at true sizes, on light and dark
    y = 380
    out.append(f'<text x="40" y="{y}" font-family="-apple-system, Helvetica Neue, Arial" font-size="15" fill="#6E6E73">'
               f'true sizes - app icon 128 / 64 / 32 / 16 (small cut where one exists at 32 and below), mono icon, mark 64 / 32 / 16 on light and dark</text>')
    x = 40
    for s in (128, 64, 32, 16):
        out.append(place(icon if s > 32 else icon_small, x, y + 20 + (128 - s), s))
        x += s + 24
    out.append(place(mono_icon, x, y + 20 + 64, 64))
    x += 64 + 40
    for s in (64, 32, 16):
        out.append(place(body(builder if s > 32 else sb, a, b), x, y + 20 + (128 - s), s))
        x += s + 20
    out.append(f'<rect x="{x}" y="{y + 10}" width="{64 + 32 + 16 + 4 * 20}" height="148" rx="12" fill="{INK}"/>')
    x += 20
    for s in (64, 32, 16):
        out.append(place(body(builder if s > 32 else sb, "#FFFFFF", "#FFFFFF"), x, y + 20 + (128 - s), s))
        x += s + 20
    out.append(f'<text x="40" y="610" font-family="-apple-system, Helvetica Neue, Arial" font-size="22" '
               f'font-weight="600" fill="{GRAPHITE}">{title}</text>')
    return svg("".join(out), title + " - preview", vb="0 0 1200 640", w=1200, h=640, defs=defs)


def main():
    for d, name, builder, cols, tile, tcols, scale in CONCEPTS:
        p = os.path.join(HERE, d)
        os.makedirs(p, exist_ok=True)
        t = f"F1 Lap Analyser - {name}"
        files = {
            "mark.svg": svg(body(builder, *cols), t),
            "mark-mono.svg": svg(body(builder, "#000000", "#000000"), t + " (one colour)"),
            "mark-reversed.svg": svg(body(builder, "#FFFFFF", "#FFFFFF"), t + " (reversed)"),
            "mark-on-dark.svg": svg(body(builder, *(tcols if tile != PAPER else ("#FFFFFF", RED))), t + " (colour, for dark backgrounds)"),
            "app-icon.svg": app_icon(builder, tile, *tcols, scale, t + " app icon"),
            "app-icon-mono.svg": app_icon(builder, tile, "#FFFFFF", "#FFFFFF", scale, t + " app icon (one colour)", mono=True),
            "preview.svg": preview(builder, cols, tile, tcols, scale, f"{d[:2]}  {name}", SMALL.get(d)),
        }
        if d in SMALL:
            files["mark-small.svg"] = svg(body(SMALL[d], *cols), t + " (small-size cut)")
            files["app-icon-small.svg"] = app_icon(SMALL[d], tile, *tcols, 0.62, t + " app icon (16-32 px cut)")
        for fn, content in files.items():
            with open(os.path.join(p, fn), "w") as fh:
                fh.write(content)
    print("written:", ", ".join(c[0] for c in CONCEPTS))


if __name__ == "__main__":
    main()
