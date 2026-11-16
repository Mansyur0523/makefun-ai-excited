#!/usr/bin/env python3
"""Skywhale — a whale swims UP through a sunset sky to touch the sun.

One image, drawn entirely by this program (Python 3.13 standard library
only, no network, no randomness, no copied assets). The program rasterises
a flat poster-style scene into a 1024x1024 RGB buffer and encodes it as a
PNG with zlib+struct.

The scene: a colossal whale rises diagonally through a deep sunset sky,
its head aimed at a blazing sun. A tiny hot-air balloon drifts nearby for
scale. The twist is the inversion — a whale does not fly, and it does not
swim upward into the sky — yet here it does, mid-stroke, about to touch
the light. One diagonal line of motion, one giant shape, one focal sun:
the image still reads at 300 pixels wide.
"""

import math
import os
import struct
import zlib

W = H = 1024

# ---------------------------------------------------------------- palette

SKY_STOPS = [  # (fraction down the frame, (r, g, b))
    (0.00, (10, 14, 46)),
    (0.30, (24, 34, 84)),
    (0.50, (62, 52, 110)),
    (0.65, (146, 64, 110)),
    (0.78, (214, 96, 74)),
    (0.88, (247, 150, 66)),
    (1.00, (252, 196, 104)),
]

SUN = (712, 318)          # sun centre
SUN_R = 88                # sun disc radius
SUN_CORE = (255, 232, 165)
SUN_MID = (255, 190, 90)
GLOW_COLOUR = (255, 176, 92)
HALO_COLOUR = (255, 210, 130)

WHALE_CENTRE = (520, 620)
WHALE_RX = 300
WHALE_RY = 135
WHALE_ANGLE = math.radians(-24)   # head rises to the upper right
WHALE_BODY = (46, 58, 103)
WHALE_BELLY = (124, 140, 196)
WHALE_RIM = (255, 196, 107)
WHALE_DARK = (10, 12, 30)

BALLOON = (845, 590)

# ---------------------------------------------------------------- canvas


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _lerp(a, b, t):
    return a + (b - a) * t


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)

    # -- low level ------------------------------------------------------

    def _blend_px(self, x, y, r, g, b, a):
        """Blend one pixel, src-over, a in 0..1."""
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            buf = self.buf
            buf[i] = int(r * a + buf[i] * (1.0 - a) + 0.5)
            buf[i + 1] = int(g * a + buf[i + 1] * (1.0 - a) + 0.5)
            buf[i + 2] = int(b * a + buf[i + 2] * (1.0 - a) + 0.5)

    def _span(self, y, x0, x1, colour):
        """Fill a horizontal run on row y with a flat colour (fast)."""
        if y < 0 or y >= self.h:
            return
        x0 = max(0, int(math.ceil(x0)))
        x1 = min(self.w - 1, int(math.floor(x1)))
        if x1 < x0:
            return
        r, g, b = colour
        i = (y * self.w + x0) * 3
        n = x1 - x0 + 1
        self.buf[i:i + n * 3] = bytes((r, g, b)) * n

    def _span_alpha(self, y, x0, x1, colour, a):
        """Fill a horizontal run with a translucent colour."""
        if y < 0 or y >= self.h or a <= 0.0:
            return
        x0 = max(0, int(math.ceil(x0)))
        x1 = min(self.w - 1, int(math.floor(x1)))
        if x1 < x0:
            return
        r, g, b = colour
        buf = self.buf
        ia = 1.0 - a
        for x in range(x0, x1 + 1):
            i = (y * self.w + x) * 3
            buf[i] = int(r * a + buf[i] * ia + 0.5)
            buf[i + 1] = int(g * a + buf[i + 1] * ia + 0.5)
            buf[i + 2] = int(b * a + buf[i + 2] * ia + 0.5)

    # -- fills ----------------------------------------------------------

    def vgrad(self, stops):
        """Vertical gradient; stops are (fraction, colour), sorted."""
        for y in range(self.h):
            t = y / (self.h - 1)
            for k in range(len(stops) - 1):
                f0, c0 = stops[k]
                f1, c1 = stops[k + 1]
                if f0 <= t <= f1:
                    u = 0.0 if f1 == f0 else (t - f0) / (f1 - f0)
                    r = int(_lerp(c0[0], c1[0], u) + 0.5)
                    g = int(_lerp(c0[1], c1[1], u) + 0.5)
                    b = int(_lerp(c0[2], c1[2], u) + 0.5)
                    break
            else:
                r, g, b = stops[-1][1]
            i = y * self.w * 3
            self.buf[i:i + self.w * 3] = bytes((r, g, b)) * self.w

    def glow(self, cx, cy, radius, colour, strength):
        """Soft radial glow; squared-distance falloff, no sqrt."""
        r2 = radius * radius
        x0 = max(0, cx - radius)
        x1 = min(self.w - 1, cx + radius)
        y0 = max(0, cy - radius)
        y1 = min(self.h - 1, cy + radius)
        cr, cg, cb = colour
        buf = self.buf
        w = self.w
        for y in range(y0, y1 + 1):
            dy = y - cy
            dy2 = dy * dy
            base = y * w * 3
            for x in range(x0, x1 + 1):
                dx = x - cx
                q = 1.0 - (dx * dx + dy2) / r2
                if q <= 0.0:
                    continue
                a = strength * q * q
                i = base + x * 3
                buf[i] = int(cr * a + buf[i] * (1.0 - a) + 0.5)
                buf[i + 1] = int(cg * a + buf[i + 1] * (1.0 - a) + 0.5)
                buf[i + 2] = int(cb * a + buf[i + 2] * (1.0 - a) + 0.5)

    def ellipse(self, cx, cy, rx, ry, colour, angle=0.0, alpha=1.0,
                edge_blend=False):
        """Scanline-filled ellipse, optionally rotated (radians).

        With edge_blend the two boundary pixels of each row are blended at
        50%, which softens the silhouette by one pixel.
        """
        c = math.cos(angle)
        s = math.sin(angle)
        inv_rx2 = 1.0 / (rx * rx)
        inv_ry2 = 1.0 / (ry * ry)
        a_coef = c * c * inv_rx2 + s * s * inv_ry2
        y0 = max(0, int(math.floor(cy - max(rx, ry))))
        y1 = min(self.h - 1, int(math.ceil(cy + max(rx, ry))))
        for y in range(y0, y1 + 1):
            dy = y - cy
            b_coef = 2.0 * c * s * dy * (inv_rx2 - inv_ry2)
            c_coef = dy * dy * (s * s * inv_rx2 + c * c * inv_ry2) - 1.0
            disc = b_coef * b_coef - 4.0 * a_coef * c_coef
            if disc < 0.0:
                continue
            root = math.sqrt(disc) / (2.0 * a_coef)
            mid = -b_coef / (2.0 * a_coef)
            xa, xb = cx + mid - root, cx + mid + root
            if alpha >= 1.0:
                self._span(y, xa, xb, colour)
                if edge_blend:
                    self._blend_px(int(math.floor(xa)) - 1, y,
                                   colour[0], colour[1], colour[2], 0.5)
                    self._blend_px(int(math.ceil(xb)) + 1, y,
                                   colour[0], colour[1], colour[2], 0.5)
            else:
                self._span_alpha(y, xa, xb, colour, alpha)

    def circle(self, cx, cy, r, colour, alpha=1.0):
        self.ellipse(cx, cy, r, r, colour, 0.0, alpha)

    def polygon(self, points, colour, alpha=1.0):
        """Even-odd scanline fill for a simple polygon."""
        ys = [p[1] for p in points]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(points)
        for y in range(y0, y1 + 1):
            xs = []
            for k in range(n):
                x1, y1p = points[k]
                x2, y2p = points[(k + 1) % n]
                if (y1p <= y < y2p) or (y2p <= y < y1p):
                    t = (y - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                if alpha >= 1.0:
                    self._span(y, xs[k], xs[k + 1], colour)
                else:
                    self._span_alpha(y, xs[k], xs[k + 1], colour, alpha)

    def disc_row(self, cx, cy, r, y, colour):
        """One row of a small filled circle (helper for dots/lines)."""
        dy = y - cy
        if abs(dy) > r:
            return
        half = math.sqrt(r * r - dy * dy)
        self._span(y, cx - half, cx + half, colour)


# ---------------------------------------------------------------- whale

def _local_to_global(cx, cy, angle, lx, ly):
    """Whale-local coords -> frame coords. +x toward the head, +y belly."""
    c = math.cos(angle)
    s = math.sin(angle)
    return (cx + c * lx - s * ly, cy + s * lx + c * ly)


def draw_whale(cv):
    cx, cy = WHALE_CENTRE
    ang = WHALE_ANGLE
    u = (math.cos(ang), math.sin(ang))       # toward head
    v = (-math.sin(ang), math.cos(ang))      # toward belly
    pt = lambda lx, ly: _local_to_global(cx, cy, ang, lx, ly)

    # tail stock + flukes (drawn first so the body covers the joint)
    stock = [pt(-290, -30), pt(-290, 30), pt(-425, 20),
             pt(-452, 0), pt(-425, -20)]
    cv.polygon(stock, WHALE_BODY)
    fluke_up = [pt(-438, -10), pt(-475, -62), pt(-505, 4)]
    fluke_dn = [pt(-438, 10), pt(-470, 66), pt(-498, 2)]
    cv.polygon(fluke_up, WHALE_BODY)
    cv.polygon(fluke_dn, WHALE_BODY)

    # rim light: a gold ellipse peeking out above the body's top edge
    rim_c = (cx - v[0] * 5, cy - v[1] * 5)
    cv.ellipse(rim_c[0], rim_c[1], WHALE_RX, WHALE_RY, WHALE_RIM, ang)
    # belly: a pale ellipse peeking out below the body's bottom edge
    belly_c = (cx + v[0] * 26, cy + v[1] * 26)
    cv.ellipse(belly_c[0], belly_c[1], WHALE_RX - 10, WHALE_RY - 8,
               WHALE_BELLY, ang)
    # body
    cv.ellipse(cx, cy, WHALE_RX, WHALE_RY, WHALE_BODY, ang,
               edge_blend=True)

    # pectoral fin, tucked under the body, pointing back-down
    fin = [pt(70, 55), pt(130, 120), pt(165, 95), pt(110, 48)]
    cv.polygon(fin, (38, 48, 88))

    # eye — one dark dot, high on the head
    ex, ey = pt(252, -38)
    cv.circle(int(ex), int(ey), 7, WHALE_DARK)


# ---------------------------------------------------------------- scene


def _lcg(seed):
    """Tiny deterministic generator (no random module, no time)."""
    state = seed
    while True:
        state = (1103515245 * state + 12345) % 2147483648
        yield state / 2147483648


def draw_scene(cv):
    cv.vgrad(SKY_STOPS)

    # stars, denser and brighter near the top
    rng = _lcg(20261116)
    for _ in range(150):
        x = int(next(rng) * W)
        y = int(next(rng) * next(rng) * 560)
        bright = 140 + int(next(rng) * 115)
        r = 1 if next(rng) < 0.75 else 2
        col = (bright, bright, min(255, bright + 15))
        cv.circle(x, y, r, col)

    # sun glow, then the disc
    cv.glow(SUN[0], SUN[1], 340, GLOW_COLOUR, 0.50)
    cv.glow(SUN[0], SUN[1], 150, HALO_COLOUR, 0.35)
    cv.circle(SUN[0], SUN[1], SUN_R, SUN_MID)
    cv.circle(SUN[0], SUN[1], 62, SUN_CORE)

    # soft clouds behind the whale — small clustered puffs, never flat discs
    for (x, y, rx, ry, col, a) in (
            (150, 300, 90, 26, (232, 160, 180), 0.18),
            (230, 285, 110, 30, (232, 160, 180), 0.18),
            (300, 305, 80, 24, (232, 160, 180), 0.16),
            (780, 175, 90, 24, (200, 170, 220), 0.16),
            (860, 165, 100, 26, (200, 170, 220), 0.16),
            (920, 180, 70, 20, (200, 170, 220), 0.14),
            (640, 120, 110, 22, (205, 175, 225), 0.14)):
        cv.ellipse(x, y, rx, ry, col, 0.0, a)

    # speed streaks trailing behind the tail — the whale is moving fast
    for (x0, y0, x1, y1) in (
            (150, 860, 260, 820), (180, 890, 280, 855),
            (120, 830, 210, 795)):
        cv.polygon([(x0, y0), (x1, y1), (x1, y1 + 4), (x0, y0 + 4)],
                   (255, 235, 210), 0.40)

    draw_whale(cv)

    # low warm clouds in front of the whale's lower edge — clustered puffs
    for (x, y, rx, ry, col, a) in (
            (200, 815, 120, 30, (240, 150, 120), 0.20),
            (290, 800, 130, 34, (240, 150, 120), 0.20),
            (360, 820, 90, 26, (240, 150, 120), 0.18),
            (700, 860, 110, 28, (238, 158, 128), 0.18),
            (790, 850, 120, 30, (238, 158, 128), 0.18),
            (860, 865, 80, 24, (238, 158, 128), 0.16),
            (60, 880, 120, 26, (235, 155, 125), 0.15)):
        cv.ellipse(x, y, rx, ry, col, 0.0, a)

    # birds scattering away from the whale's path
    for (x, y, s) in ((140, 180, 9), (210, 150, 7), (280, 205, 8),
                      (330, 130, 6), (120, 260, 7), (380, 180, 6)):
        cv.polygon([(x - s, y), (x, y - s * 0.55), (x + s, y)],
                   (20, 20, 50), 0.85)

    # tiny hot-air balloon for scale — the whale is enormous next to it
    bx, by = BALLOON
    cv.polygon([(bx - 4, by + 22), (bx + 4, by + 22),
                (bx + 2, by + 30), (bx - 2, by + 30)], (90, 50, 40))
    cv.polygon([(bx - 3, by + 12), (bx + 3, by + 12),
                (bx + 2, by + 22), (bx - 2, by + 22)], (60, 35, 30))
    cv.circle(bx, by, 20, (235, 90, 70))
    cv.circle(bx, by - 4, 12, (255, 150, 90))
    cv.ellipse(bx, by, 20, 20, (235, 90, 70))

    # city skyline, tiny at the very bottom — the world the whale left
    cv.polygon([(0, 1024), (0, 990), (1024, 990), (1024, 1024)],
               (16, 14, 40))
    rng2 = _lcg(777)
    x = 0
    while x < W:
        bw = 34 + int(next(rng2) * 46)
        bh = 18 + int(next(rng2) * 42)
        cv.polygon([(x, 990), (x, 990 - bh), (x + bw, 990 - bh),
                    (x + bw, 990)], (16, 14, 40))
        for wy in range(990 - bh + 8, 986, 12):
            for wx in range(x + 7, x + bw - 5, 12):
                if next(rng2) < 0.45:
                    cv.polygon([(wx, wy), (wx + 4, wy), (wx + 4, wy + 5),
                                (wx, wy + 5)], (255, 200, 110))
        x += bw + 6


# ---------------------------------------------------------------- PNG

def encode_png(cv):
    """PNG, filter 0 (None), zlib level 9 — deterministic bytes."""
    w, h = cv.w, cv.h
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += cv.buf[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    return png


def main():
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(outdir, exist_ok=True)
    cv = Canvas(W, H)
    draw_scene(cv)
    data = encode_png(cv)
    with open(os.path.join(outdir, "entry.png"), "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
