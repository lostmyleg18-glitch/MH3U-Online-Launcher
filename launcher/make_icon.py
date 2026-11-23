"""Render the launcher's shield-and-claws emblem to mh3u_play.ico (stdlib only).

Same shapes as the <symbol id="emblem"> in ui/index.html. Anti-aliased scanline fill.
"""
import math
import struct
import sys
import zlib
from pathlib import Path

OUTER = "M60 3 L112 17 L112 61 C112 99 89 123 60 137 C31 123 8 99 8 61 L8 17 Z"
INNER = "M60 11 L104 23 L104 61 C104 94 85 115 60 128 C35 115 16 94 16 61 L16 23 Z"
CLAWS = ["M33 30 C43 50 49 74 45 108 C43 82 35 58 26 37 Z",
         "M57 26 C67 50 72 78 66 116 C64 86 57 59 49 33 Z",
         "M81 30 C89 49 92 72 85 102 C85 78 79 56 72 37 Z"]
GOLD = [(0, (255, 246, 200)), (.3, (242, 207, 106)), (.62, (185, 131, 44)), (1, (110, 70, 18))]
IRON = [(0, (59, 51, 44)), (.55, (26, 21, 18)), (1, (12, 10, 8))]
EMBER = [(0, (255, 231, 168)), (.4, (255, 155, 61)), (1, (196, 39, 15))]


def parse(d):
    toks = d.replace(",", " ").split()
    pts, i, cur = [], 0, (0.0, 0.0)
    while i < len(toks):
        c = toks[i]
        if c in "ML":
            cur = (float(toks[i + 1]), float(toks[i + 2]))
            pts.append(cur)
            i += 3
        elif c == "C":
            p1 = (float(toks[i + 1]), float(toks[i + 2]))
            p2 = (float(toks[i + 3]), float(toks[i + 4]))
            p3 = (float(toks[i + 5]), float(toks[i + 6]))
            for k in range(1, 25):
                t = k / 24
                a, b, c2, e = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
                pts.append((a * cur[0] + b * p1[0] + c2 * p2[0] + e * p3[0],
                            a * cur[1] + b * p1[1] + c2 * p2[1] + e * p3[1]))
            cur = p3
            i += 7
        else:          # Z
            i += 1
    return pts


def coverage(poly, size, scale, ox, oy, ss=4):
    cov = [[0.0] * size for _ in range(size)]
    pts = [(x * scale + ox, y * scale + oy) for x, y in poly]
    edges = list(zip(pts, pts[1:] + pts[:1]))
    for sy in range(size * ss):
        y = (sy + 0.5) / ss
        xs = []
        for (x0, y0), (x1, y1) in edges:
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        row = cov[sy // ss]
        for a, b in zip(xs[0::2], xs[1::2]):
            a, b = max(a, 0.0), min(b, float(size))
            for px in range(int(math.floor(a)), int(math.ceil(b))):
                ov = min(b, px + 1) - max(a, px)
                if ov > 0:
                    row[px] += ov / ss
    return cov


def grad(stops, t):
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return tuple(c0[i] + (c1[i] - c0[i]) * f for i in range(3))
    return stops[-1][1]


def blur(cov, r):
    if r < 1:
        return cov
    n = len(cov)
    out = cov
    for _ in range(2):
        tmp = [[0.0] * n for _ in range(n)]
        for y in range(n):
            row, acc = out[y], 0.0
            for x in range(n):
                lo, hi = max(0, x - r), min(n - 1, x + r)
                tmp[y][x] = sum(row[lo:hi + 1]) / (2 * r + 1)
        out2 = [[0.0] * n for _ in range(n)]
        for x in range(n):
            for y in range(n):
                lo, hi = max(0, y - r), min(n - 1, y + r)
                out2[y][x] = sum(tmp[k][x] for k in range(lo, hi + 1)) / (2 * r + 1)
        out = out2
    return out


def render(size):
    scale = size * 0.94 / 140
    ox, oy = (size - 120 * scale) / 2, (size - 140 * scale) / 2
    outer = coverage(parse(OUTER), size, scale, ox, oy)
    inner = coverage(parse(INNER), size, scale, ox, oy)
    claws = [[0.0] * size for _ in range(size)]
    for d in CLAWS:
        c = coverage(parse(d), size, scale, ox, oy)
        for y in range(size):
            for x in range(size):
                claws[y][x] = min(1.0, claws[y][x] + c[y][x])
    glow = blur(claws, max(1, size // 64))
    px = bytearray()
    top, h = oy + 3 * scale, 134 * scale
    for y in range(size):
        t = (y + .5 - top) / h
        g, i_, e = grad(GOLD, t), grad(IRON, t), grad(EMBER, (y + .5 - (oy + 26 * scale)) / (90 * scale))
        px.append(0)            # PNG filter byte
        for x in range(size):
            a_out = min(1.0, outer[y][x])
            r, gg, b = g
            ai = min(1.0, inner[y][x])
            r, gg, b = (r + (i_[0] - r) * ai, gg + (i_[1] - gg) * ai, b + (i_[2] - b) * ai)
            gl = min(1.0, glow[y][x] * 0.7) * ai
            r, gg, b = (r + (255 - r) * gl * .55, gg + (120 - gg) * gl * .55, b + (40 - b) * gl * .55)
            ac = min(1.0, claws[y][x])
            r, gg, b = (r + (e[0] - r) * ac, gg + (e[1] - gg) * ac, b + (e[2] - b) * ac)
            px += bytes((int(r), int(gg), int(b), int(a_out * 255)))
    return png(size, bytes(px))


def png(size, raw):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main(out):
    sizes = [256, 64, 48, 32, 16]
    images = [render(s) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, img in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
        blobs += img
    Path(out).write_bytes(head + entries + blobs)
    Path(out).with_suffix(".png").write_bytes(images[0])
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mh3u_play.ico")
