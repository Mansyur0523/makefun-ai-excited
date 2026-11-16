#!/usr/bin/env python3
"""Skywhale — a colossal whale swims up through a sunset sky to touch the sun.

Procedural, deterministic, Python 3.13 standard library only (no network).
Writes one 1024x1024 PNG to /output/entry.png (or $MAKEFUN_OUTPUT_DIR).
"""

import math
import os
import random
import struct
import zlib

W = 1024
H = 1024

# ---------------------------------------------------------------- pixel buffer
buf = bytearray(W * H * 3)


def _idx(x, y):
    return (y * W + x) * 3


def set_px(x, y, r, g, b):
    if 0 <= x < W and 0 <= y < H:
        i = _idx(x, y)
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b


def fill_span(y, x0, x1, r, g, b):
    if y < 0 or y >= H:
        return
    x0 = max(0, int(x0))
    x1 = min(W - 1, int(x1))
    if x1 < x0:
        return
    i = _idx(x0, y)
    n = x1 - x0 + 1
    buf[i:i + n * 3] = bytes((r, g, b)) * n


def blend_span(y, x0, x1, r, g, b, a):
    if y < 0 or y >= H:
        return
    x0 = max(0, int(x0))
    x1 = min(W - 1, int(x1))
    if x1 < x0:
        return
    inv = 1.0 - a
    for x in range(x0, x1 + 1):
        i = _idx(x, y)
        buf[i] = int(buf[i] * inv + r * a)
        buf[i + 1] = int(buf[i + 1] * inv + g * a)
        buf[i + 2] = int(buf[i + 2] * inv + b * a)


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


# ------------------------------------------------------------------- primitives
def fill_polygon(points, color, alpha=None):
    if len(points) < 3:
        return
    ys = [p[1] for p in points]
    y0 = max(0, int(math.ceil(min(ys))))
    y1 = min(H - 1, int(math.floor(max(ys))))
    n = len(points)
    for y in range(y0, y1 + 1):
        xs = []
        for i in range(n):
            x1, y1p = points[i]
            x2, y2p = points[(i + 1) % n]
            if (y1p <= y < y2p) or (y2p <= y < y1p):
                t = (y - y1p) / (y2p - y1p)
                xs.append(x1 + t * (x2 - x1))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            if alpha is None:
                fill_span(y, xs[k], xs[k + 1], *color)
            else:
                blend_span(y, xs[k], xs[k + 1], *color, alpha)


def fill_circle(cx, cy, rad, color, alpha=None):
    r = int(rad)
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        dy = y - cy
        dx = int(math.sqrt(max(0, rad * rad - dy * dy)))
        if alpha is None:
            fill_span(y, cx - dx, cx + dx, *color)
        else:
            blend_span(y, cx - dx, cx + dx, *color, alpha)


def fill_ellipse(cx, cy, rx, ry, color, alpha=None):
    for y in range(max(0, int(cy - ry)), min(H, int(cy + ry) + 1)):
        t = (y - cy) / ry
        dx = int(rx * math.sqrt(max(0.0, 1.0 - t * t)))
        if alpha is None:
            fill_span(y, cx - dx, cx + dx, *color)
        else:
            blend_span(y, cx - dx, cx + dx, *color, alpha)


def thick_line(x0, y0, x1, y1, width, color, alpha=None):
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    steps = max(1, int(length))
    rad = width / 2.0
    for s in range(steps + 1):
        t = s / steps
        fill_circle(int(x0 + dx * t), int(y0 + dy * t), rad, color, alpha)


def polyline(points, width, color, alpha=None):
    for i in range(len(points) - 1):
        thick_line(points[i][0], points[i][1],
                   points[i + 1][0], points[i + 1][1], width, color, alpha)


# ------------------------------------------------------------------------- sky
SKY_STOPS = [
    (0, (24, 14, 48)),      # deep indigo
    (330, (92, 36, 90)),    # violet
    (600, (198, 72, 94)),   # rose
    (800, (255, 122, 47)),  # burning orange horizon
    (930, (120, 44, 62)),   # dusk band above the city
    (1024, (40, 20, 44)),
]


def sky_color(y):
    for i in range(len(SKY_STOPS) - 1):
        y0, c0 = SKY_STOPS[i]
        y1, c1 = SKY_STOPS[i + 1]
        if y0 <= y <= y1:
            t = (y - y0) / max(1, y1 - y0)
            return lerp_color(c0, c1, t)
    return SKY_STOPS[-1][1]


def draw_sky():
    for y in range(H):
        r, g, b = sky_color(y)
        i = y * W * 3
        buf[i:i + W * 3] = bytes((r, g, b)) * W


SUN_X, SUN_Y = 700, 250


def draw_stars():
    rng = random.Random(11)
    for _ in range(150):
        x = rng.randint(0, W - 1)
        y = rng.randint(0, 430)
        if math.hypot(x - SUN_X, y - SUN_Y) < 130:
            continue
        br = rng.randint(150, 255)
        s = rng.random()
        set_px(x, y, br, br, min(255, br + 10))
        if s > 0.7:
            set_px(x + 1, y, br // 2, br // 2, br // 2)


def draw_sun():
    # wide soft glow, then the disc
    for rad, a in ((300, 0.05), (260, 0.07), (220, 0.09), (180, 0.12),
                   (150, 0.16), (120, 0.22), (100, 0.30)):
        fill_circle(SUN_X, SUN_Y, rad, (255, 170, 90), alpha=a)
    # faint rays
    for ang_deg in (18, 52, 108, 152, 205, 250, 295, 335):
        ang = math.radians(ang_deg)
        dx, dy = math.cos(ang), math.sin(ang)
        px, py = SUN_X + dx * 95, SUN_Y + dy * 95
        qx, qy = SUN_X + dx * 330, SUN_Y + dy * 330
        nx, ny = -dy * 7, dx * 7
        fill_polygon([(px + nx, py + ny), (px - nx, py - ny),
                      (qx - nx * 0.4, qy - ny * 0.4),
                      (qx + nx * 0.4, qy + ny * 0.4)],
                     (255, 200, 120), alpha=0.06)
    fill_circle(SUN_X, SUN_Y, 82, (255, 214, 106))
    fill_circle(SUN_X, SUN_Y, 64, (255, 240, 190))
    fill_circle(SUN_X, SUN_Y, 48, (255, 250, 220))


def draw_clouds():
    for cx, cy, rx, ry, a in (
            (180, 300, 180, 26, 0.20),
            (860, 170, 150, 22, 0.16),
            (420, 560, 220, 30, 0.18),
            (905, 620, 170, 24, 0.16),
            (120, 700, 150, 22, 0.14)):
        fill_ellipse(cx, cy, rx, ry, (255, 150, 160), alpha=a)
        fill_ellipse(cx, cy + 10, rx * 0.8, ry * 0.7, (150, 70, 130), alpha=a * 0.7)


# ----------------------------------------------------------------------- whale
TAIL = (315.0, 775.0)
D = (345.0, -375.0)
D_LEN = math.hypot(*D)
U = (D[0] / D_LEN, D[1] / D_LEN)          # along body, tail -> head
N = (U[1], -U[0])                          # perpendicular; -N faces the sun side
# note: U=(0.677,-0.736); N=(-0.736,-0.677) points up-left (sun side)


def center(t):
    return (TAIL[0] + D[0] * t + N[0] * 46.0 * math.sin(math.pi * t),
            TAIL[1] + D[1] * t + N[1] * 46.0 * math.sin(math.pi * t))


def width_at(t):
    return 150.0 * (math.sin(math.pi * (0.05 + 0.9 * t)) ** 0.7)


BODY = (46, 74, 107)        # slate blue
BELLY = (242, 227, 200)     # pale cream
RIM = (255, 207, 92)        # gold rim light
RIM_HI = (255, 233, 168)


def whale_edges(steps=48):
    upper, lower = [], []
    for i in range(steps + 1):
        t = i / steps
        cx, cy = center(t)
        w = width_at(t) / 2.0
        upper.append((cx - N[0] * w, cy - N[1] * w))   # sun side
        lower.append((cx + N[0] * w, cy + N[1] * w))   # belly side
    return upper, lower


def draw_whale():
    upper, lower = whale_edges()
    # tail flukes first (behind the body)
    p0 = center(0.0)
    back = (p0[0] - U[0] * 30, p0[1] - U[1] * 30)
    tip_up = (back[0] - U[0] * 82 - N[0] * 72, back[1] - U[1] * 82 - N[1] * 72)
    tip_dn = (back[0] - U[0] * 82 + N[0] * 72, back[1] - U[1] * 82 + N[1] * 72)
    mid_up = (back[0] - U[0] * 42 - N[0] * 26, back[1] - U[1] * 42 - N[1] * 26)
    mid_dn = (back[0] - U[0] * 42 + N[0] * 26, back[1] - U[1] * 42 + N[1] * 26)
    fill_polygon([p0, tip_up, mid_up], BODY)
    fill_polygon([p0, tip_dn, mid_dn], BODY)
    polyline([p0, tip_up], 4, RIM, alpha=0.85)
    # body
    fill_polygon(upper + lower[::-1], BODY)
    # pale belly along the lower edge
    belly = []
    for i in range(6, 46):
        t = i / 48
        cx, cy = center(t)
        w = width_at(t) / 2.0
        belly.append((cx + N[0] * w, cy + N[1] * w))
    for i in range(45, 5, -1):
        t = i / 48
        cx, cy = center(t)
        w = width_at(t) / 2.0
        belly.append((cx + N[0] * w * 0.12, cy + N[1] * w * 0.12))
    fill_polygon(belly, BELLY, alpha=0.88)
    # pectoral fin on the belly side
    fx, fy = center(0.52)
    fin_base = (fx + N[0] * 52, fy + N[1] * 52)
    fin_tip = (fin_base[0] + N[0] * 78 + U[0] * 34,
               fin_base[1] + N[1] * 78 + U[1] * 34)
    fin_w = (fin_base[0] + U[0] * 34, fin_base[1] + U[1] * 34)
    fill_polygon([fin_base, fin_tip, fin_w], (30, 50, 75))
    # gold rim light along the sun-side edge
    polyline(upper, 6, RIM, alpha=0.85)
    polyline(upper, 2, RIM_HI, alpha=0.95)
    # eye + mouth near the head
    ex, ey = center(0.88)
    ex -= N[0] * 22
    ey -= N[1] * 22
    fill_circle(int(ex), int(ey), 6, (12, 16, 24))
    fill_circle(int(ex) - 2, int(ey) - 2, 2, (255, 255, 255))
    mouth = []
    for i in range(0, 7):
        t = 0.99 - i * 0.012
        cx, cy = center(t)
        w = width_at(t) / 2.0
        mouth.append((cx + N[0] * w * 0.55, cy + N[1] * w * 0.55))
    polyline(mouth, 3, (20, 30, 48))


def draw_streaks():
    # motion streaks trailing behind / below the whale
    for t, ln in ((0.15, 190), (0.30, 230), (0.45, 210),
                  (0.60, 250), (0.75, 200), (0.90, 160)):
        cx, cy = center(t)
        w = width_at(t) / 2.0
        sx = cx + N[0] * (w + 8)
        sy = cy + N[1] * (w + 8)
        ex = sx - U[0] * ln + N[0] * 26
        ey = sy - U[1] * ln + N[1] * 26
        thick_line(int(sx), int(sy), int(ex), int(ey), 3,
                   (255, 230, 180), alpha=0.32)


# -------------------------------------------------------------------- balloon
def draw_balloon():
    bx, by = 798, 322
    # envelope: red-orange circle with cream stripes
    fill_circle(bx, by, 26, (214, 69, 60))
    for y in range(by - 26, by + 27):
        dy = y - by
        dx = int(math.sqrt(max(0, 26 * 26 - dy * dy)))
        fill_span(y, bx - 8, bx - 2, 250, 224, 178)
        fill_span(y, bx + 2, bx + 8, 250, 224, 178)
    fill_circle(bx, by + 20, 9, (255, 190, 90))
    # ropes + basket
    thick_line(bx - 12, by + 20, bx - 6, by + 40, 1, (60, 40, 25))
    thick_line(bx + 12, by + 20, bx + 6, by + 40, 1, (60, 40, 25))
    for yy in range(by + 40, by + 49):
        fill_span(yy, bx - 7, bx + 7, 96, 62, 36)


def draw_birds():
    for x, y, s in ((250, 220, 1.0), (330, 180, 0.8), (560, 150, 1.1),
                    (880, 420, 0.9), (180, 480, 1.0), (950, 520, 0.8),
                    (420, 120, 0.9), (150, 640, 1.0), (700, 90, 0.7),
                    (620, 640, 0.9)):
        w = 8 * s
        polyline([(x - w, y), (x, y + 5 * s), (x + w, y)], 2,
                 (30, 20, 40), alpha=0.9)


# ------------------------------------------------------------------------ city
def draw_city():
    rng = random.Random(2026)
    # warm haze + horizon glow above the rooftops
    for k in range(6):
        blend_span(918 + k * 3, 0, W - 1, 255, 140, 70, 0.10 - k * 0.012)
    fill_span(936, 0, W - 1, 255, 150, 80)
    x = -10
    while x < W:
        bw = rng.randint(34, 72)
        bh = rng.randint(42, 128)
        top = 1024 - bh
        for yy in range(top, 1024):
            fill_span(yy, x, x + bw, 24, 14, 34)
        # lit windows
        for _ in range(bw * bh // 260):
            wx = x + rng.randint(4, max(4, bw - 8))
            wy = top + rng.randint(6, max(6, bh - 10))
            c = (255, 205, 110) if rng.random() > 0.25 else (140, 200, 255)
            for yy in range(wy, wy + 4):
                fill_span(yy, wx, wx + 2, *c)
        # rooftop beacon on the taller towers
        if bh > 100:
            set_px(x + bw // 2, top - 2, 255, 60, 60)
        x += bw + rng.randint(2, 10)


# ------------------------------------------------------------------------- png
def write_png(path, w, h, data):
    raw = b"".join(b"\x00" + bytes(data[y * w * 3:(y + 1) * w * 3])
                   for y in range(h))

    def chunk(typ, payload):
        c = struct.pack(">I", len(payload)) + typ + payload
        return c + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    draw_sky()
    draw_stars()
    draw_sun()
    draw_clouds()
    draw_streaks()
    draw_whale()
    draw_balloon()
    draw_birds()
    draw_city()
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "entry.png")
    size = write_png(path, W, H, buf)
    print("wrote %s (%d bytes)" % (path, size))


if __name__ == "__main__":
    main()
