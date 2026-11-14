#!/usr/bin/env python3
"""
prep-cairn-sprites.py — asset-prep for the ported cairn renderer.

Computes, ONCE, the measured alpha metadata the cairn layout engine
needs for every painted stone sprite in src/assets/cairn/:

  - frame size, alpha bbox (body), bbox/centroid offsets, alpha area
  - a 56x56 occupancy raster (contact + profile-boundary solving)
  - top profile (25 columns) and bottom profile (56 columns), in frame
    px measured from the frame's top edge
  - bearing segments per side (top/bottom/left/right): runs of roughly
    constant slope along the measured alpha profile. The layout's ONE
    generic placement rule pairs a segment of the stone below with an
    angle-compatible (<=12 deg) segment of the stone above; flat stones
    degenerate to a single wide near-flat segment.

This mirrors the study pipeline (segment_prep.py in the cairn studies,
2026-11-13): metadata is computed at prep time, never per render.
Deterministic: same PNGs in, same JSON out.

Usage:  python3 scripts/prep-cairn-sprites.py
Reads:  src/assets/cairn/*.png (the eight stone sprites)
Writes: src/vision-map/cairnSpriteData.json
"""
import json
import math
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src', 'assets', 'cairn')
OUT = os.path.join(HERE, '..', 'src', 'vision-map', 'cairnSpriteData.json')

SPRITES = [
    'pebble',
    'stone-angular',
    'stone-chunk',
    'stone-large',
    'stone-medium',
    'stone-round',
    'stone-small',
    'stone-standing',
]

# The dedicated base slab (spec section 5): April's fixed 276x132
# foundation, restored as structural support — never a member. Its
# raster is DERIVED from stone-large (the wide foundation stone)
# flattened to the slab's proportions at 2px per April unit, then
# prepped by the same pipeline, so pairing geometry and rendering use
# one consistent shape.
SLAB_NAME = 'cairn-slab'
SLAB_W_PX = 552   # 276 April units * 2
SLAB_H_PX = 264   # 132 April units * 2

ALPHA_SOLID = 128          # alpha >= this counts as painted stone
GRID = 56                  # occupancy raster pitch (cells per side)
TOP_COLS = 25              # top profile samples (study convention)
BOT_COLS = 56              # bottom profile samples (study convention)
SEG_SAMPLES = 112          # profile samples feeding segmentation
SEG_TOL_DEG = 5.0          # slope drift allowed inside one segment run
SEG_MIN_FRAC = 0.035       # shortest run, as a fraction of the profile axis
SEG_MAX = 8                # spec: 3-8 segments per side (flat stones -> 1)


def norm_ang(a):
    while a > 90:
        a -= 180
    while a <= -90:
        a += 180
    return a


def column_profile(alpha, w, h, cols, from_top):
    """For each of `cols` x-buckets: the extreme solid y (frame px)."""
    out = []
    for c in range(cols):
        x0 = int(c * w / cols)
        x1 = max(x0 + 1, int((c + 1) * w / cols))
        best = None
        rng = range(h) if from_top else range(h - 1, -1, -1)
        for y in rng:
            row = alpha[y]
            if any(row[x] >= ALPHA_SOLID for x in range(x0, x1)):
                best = y
                break
        out.append(best)
    return out


def row_profile(alpha, w, h, rows, from_left):
    """For each of `rows` y-buckets: the extreme solid x (frame px)."""
    out = []
    for r in range(rows):
        y0 = int(r * h / rows)
        y1 = max(y0 + 1, int((r + 1) * h / rows))
        best = None
        rng = range(w) if from_left else range(w - 1, -1, -1)
        for x in rng:
            if any(alpha[y][x] >= ALPHA_SOLID for y in range(y0, y1)):
                best = x
                break
        out.append(best)
    return out


def segment_profile(pts):
    """Greedy constant-slope segmentation of profile points.

    pts: list of (axis, value) with Nones already removed, axis ascending.
    Returns runs as dicts with endpoint coords in profile space plus the
    fitted angle (degrees, line angle normalized to (-90, 90]) and span
    (extent along the profile axis).
    """
    if len(pts) < 2:
        return []
    axis_span = pts[-1][0] - pts[0][0]
    min_len = max(2.0, SEG_MIN_FRAC * axis_span)
    runs = []
    start = 0
    for i in range(2, len(pts) + 1):
        seg = pts[start:i]
        # fitted slope over the run so far (least squares)
        n = len(seg)
        ma = sum(p[0] for p in seg) / n
        mv = sum(p[1] for p in seg) / n
        num = sum((p[0] - ma) * (p[1] - mv) for p in seg)
        den = sum((p[0] - ma) ** 2 for p in seg)
        slope = num / den if den > 0 else 0.0
        run_ang = math.degrees(math.atan(slope))
        # local slope of the newest step
        (a0, v0), (a1, v1) = seg[-2], seg[-1]
        local_ang = math.degrees(math.atan2(v1 - v0, a1 - a0)) if a1 > a0 else run_ang
        drift = abs(norm_ang(local_ang - run_ang))
        run_len = seg[-1][0] - seg[0][0]
        if drift > SEG_TOL_DEG and run_len >= min_len and i < len(pts):
            # close the run at the previous point; the next run starts
            # there too, so segments share endpoints (deterministic).
            runs.append(seg[:-1])
            start = i - 2
    runs.append(pts[start:])
    # merge runs shorter than min_len into their longer neighbour
    def run_len(r):
        return r[-1][0] - r[0][0]
    merged = []
    for r in runs:
        if len(r) < 2:
            continue
        if merged and run_len(r) < min_len:
            merged[-1] = merged[-1] + r[1:]
        else:
            merged.append(r)
    if merged and len(merged) > 1 and run_len(merged[0]) < min_len:
        merged[1] = merged[0] + merged[1][1:]
        merged = merged[1:]
    # cap at SEG_MAX by merging the pair with the closest fitted angles
    def fit_ang(r):
        n = len(r)
        ma = sum(p[0] for p in r) / n
        mv = sum(p[1] for p in r) / n
        num = sum((p[0] - ma) * (p[1] - mv) for p in r)
        den = sum((p[0] - ma) ** 2 for p in r)
        return math.degrees(math.atan(num / den)) if den > 0 else 0.0
    while len(merged) > SEG_MAX:
        best_i, best_d = 0, None
        for i in range(len(merged) - 1):
            d = abs(norm_ang(fit_ang(merged[i]) - fit_ang(merged[i + 1])))
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        merged[best_i] = merged[best_i] + merged[best_i + 1][1:]
        del merged[best_i + 1]
    out = []
    for r in merged:
        (a0, v0), (a1, v1) = r[0], r[-1]
        if a1 <= a0:
            continue
        n = len(r)
        ma = sum(p[0] for p in r) / n
        mv = sum(p[1] for p in r) / n
        num = sum((p[0] - ma) * (p[1] - mv) for p in r)
        den = sum((p[0] - ma) ** 2 for p in r)
        slope = num / den if den > 0 else 0.0
        # endpoints on the fitted line, at the run's axis extremes
        f0 = mv + slope * (a0 - ma)
        f1 = mv + slope * (a1 - ma)
        out.append({
            'a0': round(a0, 2), 'v0': round(f0, 2),
            'a1': round(a1, 2), 'v1': round(f1, 2),
            'ang': round(norm_ang(math.degrees(math.atan(slope))), 3),
            'span': round(a1 - a0, 2),
        })
    return out


def side_segments(alpha, w, h, side):
    """Segments for one frame side, in FRAME coordinates (x right, y down).

    top/bottom: profile value = y at axis = x.
    left/right: profile value = x at axis = y; endpoints are returned
    swapped so (x0,y0)-(x1,y1) are always true frame points.
    """
    if side in ('top', 'bottom'):
        prof = column_profile(alpha, w, h, SEG_SAMPLES, side == 'top')
        pts = [((c + 0.5) * w / SEG_SAMPLES, prof[c]) for c in range(SEG_SAMPLES)
               if prof[c] is not None]
        runs = segment_profile(pts)
        return [{'x0': r['a0'], 'y0': r['v0'], 'x1': r['a1'], 'y1': r['v1'],
                 'ang': r['ang'], 'span': r['span']} for r in runs]
    else:
        prof = row_profile(alpha, w, h, SEG_SAMPLES, side == 'left')
        pts = [((r + 0.5) * h / SEG_SAMPLES, prof[r]) for r in range(SEG_SAMPLES)
               if prof[r] is not None]
        runs = segment_profile(pts)
        # profile space is (axis=y, value=x); a segment's line angle must
        # be the angle of its direction vector (dx, dy) along +y travel.
        out = []
        for r in runs:
            dx = r['v1'] - r['v0']
            dy = r['a1'] - r['a0']
            ang = norm_ang(math.degrees(math.atan2(dy, dx)))
            out.append({'x0': r['v0'], 'y0': r['a0'], 'x1': r['v1'], 'y1': r['a1'],
                        'ang': round(ang, 3), 'span': r['span']})
        return out


def prep(name):
    path = os.path.join(SRC, name + '.png')
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    alpha = [[im.getpixel((x, y))[3] for x in range(w)] for y in range(h)]
    bbox = im.getchannel('A').getbbox()
    x0, y0, x1, y1 = bbox
    body_w, body_h = x1 - x0, y1 - y0
    # alpha area + centroid over solid pixels
    area = 0
    sx = sy = 0.0
    for y in range(h):
        row = alpha[y]
        for x in range(w):
            if row[x] >= ALPHA_SOLID:
                area += 1
                sx += x + 0.5
                sy += y + 0.5
    cen_x, cen_y = sx / area, sy / area
    # occupancy raster over the frame
    occ = []
    for gy in range(GRID):
        cy0 = int(gy * h / GRID)
        cy1 = max(cy0 + 1, int((gy + 1) * h / GRID))
        line = ''
        for gx in range(GRID):
            cx0 = int(gx * w / GRID)
            cx1 = max(cx0 + 1, int((gx + 1) * w / GRID))
            solid = any(alpha[y][x] >= ALPHA_SOLID
                        for y in range(cy0, cy1) for x in range(cx0, cx1))
            line += '1' if solid else '0'
        occ.append(line)
    top = column_profile(alpha, w, h, TOP_COLS, True)
    bottom = column_profile(alpha, w, h, BOT_COLS, False)
    return {
        'frame': [w, h],
        'bodyW': body_w,
        'bodyH': body_h,
        # body (alpha bbox) centre offset from frame centre, native px
        'bboxOff': [round((x0 + x1) / 2 - w / 2, 2), round((y0 + y1) / 2 - h / 2, 2)],
        # alpha centroid offset from frame centre, native px
        'cenOff': [round(cen_x - w / 2, 2), round(cen_y - h / 2, 2)],
        'alphaArea': area,
        'occ': occ,
        'topProfile': top,
        'bottomProfile': bottom,
        'segments': {side: side_segments(alpha, w, h, side)
                     for side in ('top', 'bottom', 'left', 'right')},
    }


def build_slab():
    src = Image.open(os.path.join(SRC, 'stone-large.png')).convert('RGBA')
    slab = src.resize((SLAB_W_PX, SLAB_H_PX), Image.LANCZOS)
    slab.save(os.path.join(SRC, SLAB_NAME + '.png'))


def main():
    build_slab()
    data = {name: prep(name) for name in SPRITES + [SLAB_NAME]}
    with open(OUT, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
        f.write('\n')
    for name in SPRITES + [SLAB_NAME]:
        d = data[name]
        print(name, 'frame', d['frame'], 'body', d['bodyW'], 'x', d['bodyH'],
              'segs', {k: len(v) for k, v in d['segments'].items()})
    print('wrote', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()
