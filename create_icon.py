#!/usr/bin/python3
"""
create_icon.py  –  Subnet Calculator icon generator

Produces icon_512.png in the same directory using only Python's
standard library (struct + zlib for PNG encoding).

The icon shows a subnet hierarchy tree:
  • Dark Catppuccin Mocha background with subtle dot-grid
  • One root node (supernet) at top  – sky blue
  • Two mid-tier nodes              – blue
  • Four leaf subnet nodes          – blue / green / peach / purple
  • Branching lines connecting each level
"""

import math
import struct
import zlib
import os

SIZE = 512  # output PNG is 512 × 512 px

# ── Colour palette (Catppuccin Mocha) ────────────────────────────────────────
BG      = (30,  30,  46)   # #1e1e2e  – base
SURF    = (49,  50,  68)   # #313244  – surface
SURF2   = (69,  71,  90)   # #45475a  – surface2
BLUE    = (137, 180, 250)  # #89b4fa
GREEN   = (166, 227, 161)  # #a6e3a1
PEACH   = (250, 179, 135)  # #fab387
PURPLE  = (203, 166, 247)  # #cba6f7
SKY     = (137, 220, 235)  # #89dceb
DARK    = (17,  17,  27)   # #11111b

BLUE_D   = (80,  140, 220)
GREEN_D  = (100, 190, 100)
PEACH_D  = (220, 140,  80)
PURPLE_D = (160,  90, 210)
SKY_D    = (60,  180, 200)

# ── Minimal PNG writer ────────────────────────────────────────────────────────

def _png_chunk(name: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def canvas_to_png(canvas: list, width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b""
    for row in canvas:
        rows += b"\x00"
        for r, g, b in row:
            rows += bytes([max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))])
    idat = zlib.compress(rows, 6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def make_canvas(w: int, h: int, bg: tuple) -> list:
    return [[list(bg) for _ in range(w)] for _ in range(h)]


# ── Anti-aliased drawing primitives ──────────────────────────────────────────

def _blend(canvas, x: int, y: int, color: tuple, alpha: float, W: int, H: int):
    if 0 <= x < W and 0 <= y < H:
        bg = canvas[y][x]
        canvas[y][x] = [
            int(bg[0] * (1 - alpha) + color[0] * alpha),
            int(bg[1] * (1 - alpha) + color[1] * alpha),
            int(bg[2] * (1 - alpha) + color[2] * alpha),
        ]


def draw_circle(canvas, cx: float, cy: float, radius: float,
                color: tuple, W: int, H: int, inner_r: float = 0):
    rr = int(radius) + 2
    for y in range(max(0, int(cy - rr)), min(H, int(cy + rr + 1))):
        for x in range(max(0, int(cx - rr)), min(W, int(cx + rr + 1))):
            d = math.hypot(x - cx, y - cy)
            if d < radius - 1:
                if d > inner_r:
                    _blend(canvas, x, y, color, 1.0, W, H)
            elif d < radius + 1:
                a = (radius + 1 - d) / 2
                if d > inner_r:
                    _blend(canvas, x, y, color, a, W, H)
            if inner_r > 0 and d < inner_r + 1 and d > inner_r - 1:
                a = (d - inner_r + 1) / 2
                if a > 0:
                    _blend(canvas, x, y, color, a, W, H)


def draw_line(canvas, x1: float, y1: float, x2: float, y2: float,
              color: tuple, thickness: float, W: int, H: int):
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    steps = max(1, int(length))
    half  = thickness / 2
    for i in range(steps + 1):
        t  = i / steps
        mx = x1 + t * dx
        my = y1 + t * dy
        r  = int(half) + 2
        for ty in range(max(0, int(my - r)), min(H, int(my + r + 1))):
            for tx in range(max(0, int(mx - r)), min(W, int(mx + r + 1))):
                d = math.hypot(tx - mx, ty - my)
                if d < half - 0.5:
                    _blend(canvas, tx, ty, color, 1.0, W, H)
                elif d < half + 0.5:
                    _blend(canvas, tx, ty, color, half + 0.5 - d, W, H)


def draw_gradient_bg(canvas, W, H, top_color, bottom_color):
    for y in range(H):
        t = y / (H - 1)
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        for x in range(W):
            canvas[y][x] = [r, g, b]


def draw_dot_grid(canvas, W, H, spacing: int, color: tuple, alpha: float):
    """Subtle dot grid – suggests an addressing table."""
    for y in range(spacing, H - spacing, spacing):
        for x in range(spacing, W - spacing, spacing):
            _blend(canvas, x, y, color, alpha, W, H)


# ── Main icon design ──────────────────────────────────────────────────────────

def build_icon(W: int = SIZE, H: int = SIZE) -> list:
    canvas = make_canvas(W, H, BG)

    # Gradient background
    draw_gradient_bg(canvas, W, H, top_color=(22, 22, 35), bottom_color=(14, 14, 22))

    # Subtle dot grid (very faint)
    draw_dot_grid(canvas, W, H, spacing=32, color=SURF2, alpha=0.25)

    # ── Tree node positions ───────────────────────────────────────────────────
    #   Level 0 (root):  1 node  – supernet
    #   Level 1 (mid):   2 nodes – first split
    #   Level 2 (leaf):  4 nodes – final subnets

    # Vertical positions
    y0 = H * 0.15    # root
    y1 = H * 0.47    # mid
    y2 = H * 0.80    # leaves

    # Horizontal positions
    x_root  = W * 0.50
    x_mid_l = W * 0.28
    x_mid_r = W * 0.72
    x_l1    = W * 0.115
    x_l2    = W * 0.375
    x_l3    = W * 0.625
    x_l4    = W * 0.885

    # Node radii
    r0 = W * 0.095   # root  – biggest
    r1 = W * 0.074   # mid
    r2 = W * 0.058   # leaves

    # Glow radii (drawn first, behind lines)
    def glow_color(c):
        return tuple(int(c[i] * 0.18 + BG[i] * 0.82) for i in range(3))

    # ── Lines (drawn below nodes) ─────────────────────────────────────────────
    line_col = SURF2
    lw = 7  # line width

    # Root → mid
    draw_line(canvas, x_root, y0, x_mid_l, y1, line_col, lw, W, H)
    draw_line(canvas, x_root, y0, x_mid_r, y1, line_col, lw, W, H)

    # Mid → leaves
    draw_line(canvas, x_mid_l, y1, x_l1, y2, line_col, lw, W, H)
    draw_line(canvas, x_mid_l, y1, x_l2, y2, line_col, lw, W, H)
    draw_line(canvas, x_mid_r, y1, x_l3, y2, line_col, lw, W, H)
    draw_line(canvas, x_mid_r, y1, x_l4, y2, line_col, lw, W, H)

    # ── Small junction dots at line midpoints ─────────────────────────────────
    def midpoint_dot(x1, y1, x2, y2, color):
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        draw_circle(canvas, mx, my, 6, color, W, H)

    midpoint_dot(x_root,  y0, x_mid_l, y1, BLUE)
    midpoint_dot(x_root,  y0, x_mid_r, y1, BLUE)
    midpoint_dot(x_mid_l, y1, x_l1,    y2, GREEN)
    midpoint_dot(x_mid_l, y1, x_l2,    y2, GREEN)
    midpoint_dot(x_mid_r, y1, x_l3,    y2, PEACH)
    midpoint_dot(x_mid_r, y1, x_l4,    y2, PURPLE)

    # ── Root node (supernet) ──────────────────────────────────────────────────
    draw_circle(canvas, x_root, y0, r0 * 1.35, glow_color(SKY),  W, H)
    draw_circle(canvas, x_root, y0, r0,         SURF,              W, H)
    draw_circle(canvas, x_root, y0, r0 * 0.72,  SKY,               W, H)
    draw_circle(canvas, x_root, y0, r0 * 0.42,  SKY_D,             W, H)

    # ── Mid nodes (first split, left=blue, right=blue) ────────────────────────
    for mx, my, col, col_d in [
        (x_mid_l, y1, BLUE,  BLUE_D),
        (x_mid_r, y1, BLUE,  BLUE_D),
    ]:
        draw_circle(canvas, mx, my, r1 * 1.35, glow_color(col), W, H)
        draw_circle(canvas, mx, my, r1,          SURF,            W, H)
        draw_circle(canvas, mx, my, r1 * 0.72,   col,             W, H)
        draw_circle(canvas, mx, my, r1 * 0.42,   col_d,           W, H)

    # ── Leaf nodes (subnets) ──────────────────────────────────────────────────
    leaves = [
        (x_l1, y2, GREEN,  GREEN_D),
        (x_l2, y2, GREEN,  GREEN_D),
        (x_l3, y2, PEACH,  PEACH_D),
        (x_l4, y2, PURPLE, PURPLE_D),
    ]
    for lx, ly, col, col_d in leaves:
        draw_circle(canvas, lx, ly, r2 * 1.35, glow_color(col), W, H)
        draw_circle(canvas, lx, ly, r2,          SURF,            W, H)
        draw_circle(canvas, lx, ly, r2 * 0.72,   col,             W, H)
        draw_circle(canvas, lx, ly, r2 * 0.42,   col_d,           W, H)

    return canvas


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    here     = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(here, "icon_512.png")

    print(f"Generating {SIZE}×{SIZE} icon…", end=" ", flush=True)
    canvas   = build_icon(SIZE, SIZE)
    png_data = canvas_to_png(canvas, SIZE, SIZE)

    with open(out_path, "wb") as fh:
        fh.write(png_data)

    print(f"done → {out_path}")
    return out_path


if __name__ == "__main__":
    main()
