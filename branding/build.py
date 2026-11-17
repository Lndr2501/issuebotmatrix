"""Builds the IssueBot logo: one vector drawing, three colour tones, two icon shapes.

The mark is a bold speech bubble with the "issue open" symbol (ring with a dot) cut out of it.
It is a sibling of the Diddy logo: same tile, same gradients, same bubble tail. Output goes to
`branding/logo/` (SVG masters) and `branding/logo/png/` (1024 px renders, not committed) and the bot avatar `issuebot/assets/avatar.png`.

Usage (from the repository root): python3 branding/build.py
PNG renders need `cairosvg` (pip install cairosvg) or `rsvg-convert`. Without them only SVGs are written.
"""
import math
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "logo")
# The bot sets this image as its Matrix avatar at start (see `PROFILE` in issuebot/bot.py).
AVATAR = os.path.join(os.path.dirname(HERE), "issuebot", "assets", "avatar.png")
AVATAR_SIZE = 512
SIZE = 1024

# Per tone: tile gradient and gradient of the bubble (both top to bottom).
TONES = {
    "green": {"tile": ("#34D6A0", "#047A55"), "mark": ("#FFFFFF", "#DDF7EC")},
    "pink": {"tile": ("#FF80CA", "#E60A78"), "mark": ("#FFFFFF", "#FFE4F2")},
    "black": {"tile": ("#2F2F35", "#0C0C0E"), "mark": ("#FFFFFF", "#E4E4EA")},
}

# The mark, drawn around the centre of the icon (0,0).
BUBBLE = 330  # radius of the bubble
BUBBLE_Y = -30  # centre of the bubble; moved up so the tail is inside the visual centre
TAIL = 115  # length of the bubble tail
TAIL_ANGLES = (114, 131, 150)  # start, tip and end of the tail, degrees clockwise from 3 o'clock
TAIL_ROUND = 12  # rounding of the tail tip
RING_OUTER = 200  # the issue symbol: outer radius of the ring ...
RING_INNER = 152  # ... inner radius ... (thin ring, so it reads as the issue symbol and not as a target)
DOT = 70  # ... and radius of the dot in the middle
SYMBOL_Y = BUBBLE_Y - 5


def n(value):
    """Short number for SVG output."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def point(radius, degrees):
    a = math.radians(degrees)
    return radius * math.cos(a), BUBBLE_Y + radius * math.sin(a)


def towards(a, b, distance):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return a[0] + (b[0] - a[0]) * distance / length, a[1] + (b[1] - a[1]) * distance / length


def xy(p):
    return f"{n(p[0])} {n(p[1])}"


def circle(radius, cy):
    """A full circle around (0, cy) as a path, so it can join the other shapes in one even-odd fill."""
    return f"M{-radius} {n(cy)}a{radius} {radius} 0 1 0 {2 * radius} 0a{radius} {radius} 0 1 0 -{2 * radius} 0Z"


def bubble_path():
    """Circle with a short tail to the lower left (the same tail as Diddy's bubble)."""
    start, tip, end = (
        point(BUBBLE, TAIL_ANGLES[2]),
        point(BUBBLE + TAIL, TAIL_ANGLES[1]),
        point(BUBBLE, TAIL_ANGLES[0]),
    )
    return (
        f"M{xy(start)}L{xy(towards(tip, start, TAIL_ROUND))}Q{xy(tip)} {xy(towards(tip, end, TAIL_ROUND))}"
        f"L{xy(end)}A{BUBBLE} {BUBBLE} 0 1 0 {xy(start)}Z"
    )


def mark_path():
    """Bubble with ring and dot knocked out. Even-odd: bubble solid, ring hole, gap solid, dot hole."""
    return (
        bubble_path()
        + circle(RING_OUTER, SYMBOL_Y)
        + circle(RING_INNER, SYMBOL_Y)
        + circle(DOT, SYMBOL_Y)
    )


def squircle(x, y, size, radius, smoothing=0.6):
    """Rounded square with continuous corners (the shape of an iOS or macOS app icon)."""
    budget = size / 2
    smoothing = min(smoothing, budget / radius - 1)
    p = min((1 + smoothing) * radius, budget)
    arc = 90 * (1 - smoothing)
    arc_len = math.sin(math.radians(arc / 2)) * radius * math.sqrt(2)
    alpha = (90 - arc) / 2
    p3_p4 = radius * math.tan(math.radians(alpha / 2))
    beta = 45 * smoothing
    c = p3_p4 * math.cos(math.radians(beta))
    d = c * math.tan(math.radians(beta))
    b = (p - arc_len - c - d) / 3
    a = 2 * b
    r, s = n(radius), n(arc_len)
    abc, ab, bc = a + b + c, a + b, b + c
    return (
        f"M{n(x + size - p)} {n(y)}"
        f"c{n(a)} 0 {n(ab)} 0 {n(abc)} {n(d)}a{r} {r} 0 0 1 {s} {s}c{n(d)} {n(c)} {n(d)} {n(bc)} {n(d)} {n(abc)}"
        f"V{n(y + size - p)}"
        f"c0 {n(a)} 0 {n(ab)} {n(-d)} {n(abc)}a{r} {r} 0 0 1 -{s} {s}c{n(-c)} {n(d)} {n(-bc)} {n(d)} {n(-abc)} {n(d)}"
        f"H{n(x + p)}"
        f"c{n(-a)} 0 {n(-ab)} 0 {n(-abc)} {n(-d)}a{r} {r} 0 0 1 -{s} -{s}c{n(-d)} {n(-c)} {n(-d)} {n(-bc)} {n(-d)} {n(-abc)}"
        f"V{n(y + p)}"
        f"c0 {n(-a)} 0 {n(-ab)} {n(d)} {n(-abc)}a{r} {r} 0 0 1 {s} -{s}c{n(c)} {n(-d)} {n(bc)} {n(-d)} {n(abc)} {n(-d)}"
        "Z"
    )


def gradient(name, stops, x1, y1, x2, y2):
    return (
        f'<linearGradient id="{name}" gradientUnits="userSpaceOnUse" x1="{n(x1)}" y1="{n(y1)}" '
        f'x2="{n(x2)}" y2="{n(y2)}"><stop stop-color="{stops[0]}"/>'
        f'<stop offset="1" stop-color="{stops[1]}"/></linearGradient>'
    )


def svg(body, defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="{SIZE}" height="{SIZE}">'
        f"<title>IssueBot</title>{defs}{body}</svg>\n"
    )


def icon_svg(tone, shape):
    """shape: 'square' (full bleed, for avatars that get masked) or 'rounded' (tile with rounded corners)."""
    colors = TONES[tone]
    top, bottom = BUBBLE_Y - BUBBLE, BUBBLE_Y + BUBBLE + TAIL * 0.4
    defs = [
        gradient("tile", colors["tile"], SIZE * 0.28, 0, SIZE * 0.72, SIZE),
        gradient("mark", colors["mark"], 0, top, 0, bottom),
    ]
    if shape == "rounded":
        tile = f'<path d="{squircle(0, 0, SIZE, 230)}" fill="url(#tile)"/>'
    else:
        tile = f'<rect width="{SIZE}" height="{SIZE}" fill="url(#tile)"/>'
    placed = f'<g transform="translate(512 540)"><path fill-rule="evenodd" d="{mark_path()}" fill="url(#mark)"/></g>'
    return svg(tile + placed, f'<defs>{"".join(defs)}</defs>')


def mark_svg():
    """The bare bubble in one colour (`currentColor`), for places without the coloured tile."""
    return svg(
        '<g transform="translate(512 540) scale(1.3)" fill="currentColor">'
        f'<path fill-rule="evenodd" d="{mark_path()}"/></g>'
    )


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def render_png(svg_path, png_path, size=SIZE):
    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), svg_path, "-o", png_path], check=True)
        return True
    try:
        import cairosvg
    except ImportError:
        return False
    cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=size, output_height=size)
    return True


def main():
    files = []
    for tone in TONES:
        for shape in ("square", "rounded"):
            path = os.path.join(OUT, f"issuebot-{tone}-{shape}.svg")
            write(path, icon_svg(tone, shape))
            files.append(path)
    mark = os.path.join(OUT, "issuebot-mark.svg")
    write(mark, mark_svg())
    files.append(mark)
    print(f"wrote {len(files)} SVG files to {os.path.relpath(OUT)}")

    done = 0
    for path in files:
        png = os.path.join(OUT, "png", os.path.basename(path)[:-4] + ".png")
        done += render_png(path, png)
    if done:
        print(f"rendered {done} PNG files to {os.path.relpath(os.path.join(OUT, 'png'))}")
        render_png(os.path.join(OUT, "issuebot-green-square.svg"), AVATAR, AVATAR_SIZE)
        print(f"rendered the bot avatar to {os.path.relpath(AVATAR)}")
    else:
        print("no rsvg-convert or cairosvg found, skipping PNG renders")


if __name__ == "__main__":
    main()
