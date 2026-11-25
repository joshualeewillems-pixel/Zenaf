#!/usr/bin/env python3
"""Atelier stage generation — the Well's true-prefix formation ladders.

Regenerates the Atelier's formation imagery from the canonical
geometry, replacing the shipped reveal approximation (PR #414's
deferral, closed by the founder's 2026-11-25 ruling: "build the real
thing.. there shouldn't be buttons to press, the imagery is supposed
to represent system data").

For each voice, a ladder of K=12 stage densities is accumulated in
the formation's TRUE growth order, using the canonical machinery
verbatim — nothing is redrawn:

  valen    : build_pure's Koch wave construction (13 waves vs zero),
             drawn with the expedition's certified draw_fast in
             segment-stream order; stage = first N segments.
  maeve    : build_pure's ring order (boundary, 3 seeds, then the
             Apollonian candidates in stored order), drawn with
             draw_fast_maeve ring by ring; stage = first N rings.
  jynx     : the full Penrose segment stream (interleaved-world/
             jynx_full_stream.npz) via draw_fast_jynx; stage = first
             N segments.
  severine : build_recovery2.severine_probes(zero) instrumented per
             square (the progressive-severine runner, verbatim);
             stage = state after square N. Zero recorded ink: no
             probe ever parts.
  aria     : build_pure's Julia distance-band loop; a point's
             distance is fixed at the iteration it escapes and
             unescaped points contribute zero, so the band after
             iteration N is a true prefix; stage = band at iter N.
  rumi     : the directional study's own snapshot sequence
             (grow_fern_fan + compose4), CARDINALS ONLY since the
             founder's 2026-11-25 ruling (below), sampled at 12
             frames; final == the cardinals-only study growth.
  lucian   : the directional study's grow_channels snapshot
             sequence, same treatment (the study grammar IS the
             canonical source for his pure layer — build_pure
             reuses its final).

Every ladder's final density is gated by sha256 against
atelier-timing/pure-composite/geometry-pure-hashes.json — the same
hashes build_pure produced. A voice whose final does not match is a
hard failure: this script stops rather than ship an approximation.
The one exception is Rumi, whose canonical geometry the founder
changed (next paragraph): his gate is the pinned in-repo hash
RUMI_CARDINALS_ONLY_SHA256.

RUMI, CARDINALS ONLY (founder ruling 2026-11-25, "Yes, get rid of
diagonals this looks better"): Rumi's canonical formation loses its
rim-rooted inward DIAGONAL family; the cardinals-only growth becomes
canonical. This supersedes the Rumi half of the 2026-11-24
directional-compositions ruling. LUCIAN IS NOT TOUCHED — his
inverted construction, diagonals included, stands. Rumi's fill is
regenerated with it: his region mask is recomputed from the new
density by build_pure's own region code (shape_of, verbatim — the
code that produced regions-pure's rumi mask from the superseded
density), so the fill washes the regions his remaining ink actually
encloses. The proofs that the machinery is the canonical machinery
(cardinals + diagonals recomposed == the superseded canonical
geometry, bit-exact; shape_of(superseded density) == regions-pure's
stored rumi mask, bit-exact) are re-runnable:
stagegen/verify_rumi_cardinals.py.

Rendering is build_pure's stage4m ink math verbatim (ink_layer);
Aria's final stage additionally carries her outline, composited
over the band ink exactly as build_pure's layer export does (the
outline is a finishing treatment — intermediate stages are band
ink alone). The fill splits are regenerated with build_pure's own
fill_layer / aria_lighten_layer constructions (solid voice colour
at the baked opacity over the regions-pure mask — for Rumi, over
the region mask recomputed from his current density, above;
Lucian's alternate-compartment mask; Aria's white lighten at 0.5),
replacing PR #414's un-composited splits — for Rumi the shipped
ink split is
provably contaminated by fill bleed (his ink colour equals his
fill colour, so the un-compositing was ill-conditioned; the bleed
pixels lie 100% inside his region mask where true ink is ~0).
The composed final (stage-12 ink over regenerated fill) is
verified against the canonical layer-<voice>.png exports.

Outputs (all under frontend/src/aria-atelier/):
  assets/stages/stage-<voice>-<1..12>.png   (1..11 at 400x528,
                                             12 at 1000x1320)
  assets/layer-<voice>-fill.png             (regenerated splits)
  stage-manifest.json                       (verification record)
  stageImages.ts                            (generated imports)

Resampling: all resizes are premultiplied in float32 (PIL's uint8
RGBA resize quantizes premultiplied colour at low alpha, spraying
RGB noise across transparent pixels — invisible on screen, but it
bloats every file and dirties edge colours; the float path is the
mathematically clean version of the same operation, and pixels
with no ink get the layer's shipped absent colour — black for
ink, the flat voice colour for fill, as the shipped splits carry
them; at alpha 0 the choice is invisible either way). The final stage
is resized with Lanczos, as build_pure produced the shipped
layers (its comparison target). Intermediate stages use bilinear
resampling, whose weights are all positive — so the rendered
alpha ladder inherits the density ladder's monotonicity EXACTLY
(stage k's ink is a pixelwise subset of stage k+1's), which
Lanczos's negative lobes would break by ringing (measured:
decreases up to 42/255). The drawing is transient; the standing
final stage is full-fidelity.

Run: python3 generate_stages.py            (from anywhere; ~1 min)
     python3 generate_stages.py --voice rumi
         (regenerate one voice only; the other voices' manifest
         entries and assets are preserved untouched)
"""
import hashlib, importlib.util, json, math, pathlib, sys, time
import numpy as np
from PIL import Image
from scipy import ndimage

T0 = time.time()
HOME = pathlib.Path.home()
TIMING = HOME / 'workspace/atelier-timing'
DEMO = HOME / 'workspace/rendering-test-assets/atelier-demo'
PURE = TIMING / 'pure-composite'
EXP = TIMING / 'expedition'
IW = TIMING / 'interleaved-world'
STUDY = TIMING / 'directional-growth-study'
HERE = pathlib.Path(__file__).resolve().parent
ATELIER = HERE.parent
ASSETS = ATELIER / 'assets'
STAGES_DIR = ASSETS / 'stages'
STAGES_DIR.mkdir(exist_ok=True)

K = 12
MID_SIZE = (400, 528)
FINAL_SIZE = (1000, 1320)
W, H = 1500, 1980
DARK = np.array([43, 29, 18], np.float32)
VOICES = ['rumi', 'valen', 'maeve', 'lucian', 'aria', 'severine', 'jynx']
KEY = {'severine': 'severine_probes'}
PARAMS = {  # build_pure INK_ORDER, verbatim
    'rumi': ((146, 182, 146), 0.8, 0.55),
    'valen': ((226, 78, 78), 0.75, 0.62),
    'maeve': ((172, 124, 91), 0.8, 0.5),
    'lucian': ((92, 156, 234), 0.8, 0.55),
    'aria': ((136, 146, 195), 0.9, 0.5),
    'jynx': ((165, 92, 206), 0.85, 0.55),
    'severine': ((162, 154, 193), 0.85, 0.5),
}
OPACITY = {'rumi': 0.8, 'valen': 0.5, 'maeve': 0.3, 'lucian': 0.2,
           'jynx': 0.2, 'severine': 0.1}  # build_pure OPACITY (aria: lighten 0.5)

def log(msg):
    print('[%6.1fs] %s' % (time.time() - T0, msg), flush=True)

def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def bounds(total, k=K):
    """Stage boundaries: cumulative work counts, last == total."""
    out = []
    for j in range(1, k + 1):
        b = int(round(j * total / k))
        out.append(min(total, max(1, b)))
    out[-1] = total
    return out

# ---------- canonical sources ----------
src = open(DEMO / 'build_recovery2.py').read()
head = src[:src.index('world = build_world()')]
g = {'__file__': str(DEMO / 'build_recovery2.py'), '__name__': 'build_recovery2'}
exec(head, g)
at, splat, SS = g['at'], g['splat'], g['SS']
CX, CY = 750.0, 990.0
zero = np.zeros((H, W), np.float32)

fv = load_mod('draw_fast', EXP / 'draw_fast.py')
fm = load_mod('draw_fast_maeve', EXP / 'draw_fast_maeve.py')
fj = load_mod('draw_fast_jynx', EXP / 'draw_fast_jynx.py')

geo = np.load(PURE / 'geometry-pure.npz')
reg = np.load(PURE / 'regions-pure.npz')
HASHES = json.loads((PURE / 'geometry-pure-hashes.json').read_text())['geometry-pure.npz']

# Rumi's canonical density since the founder's 2026-11-25 ruling:
# compose4(grow_fern_fan(cardinal specs)) from the directional
# study, grown by the study machinery itself. Provenance is
# re-provable by stagegen/verify_rumi_cardinals.py, which also
# re-proves that the superseded canonical (HASHES['rumi']) is the
# same growth with the diagonal family recomposed, bit-exact.
RUMI_CARDINALS_ONLY_SHA256 = '7233eafb5b5572a4c737c7608c02081b170d380772605c8f9fc9693fe12814b9'

def expected_canonical_sha(voice, key):
    if voice == 'rumi':
        return RUMI_CARDINALS_ONLY_SHA256
    return HASHES[key]

def shape_of(dens, gam):
    """build_pure's region code for Rumi (stage2), verbatim: the
    dilated ink plus every enclosed hole up to the size cap."""
    d = np.power(np.clip(dens, 0, None), gam)
    ink = ndimage.binary_dilation(d > 0.04, iterations=2)
    del d
    lab, n = ndimage.label(~ink)
    if n == 0:
        return ink
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    border_ids = np.unique(np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]]))
    cap = 0.06 * H * W
    lut = (sizes <= cap)
    lut[0] = False
    lut[border_ids] = False
    fill = lut[lab]
    del lab
    return ink | fill

# Region masks recomputed from a voice's CURRENT density instead of
# the stored regions-pure mask. Rumi only: since the 2026-11-25
# ruling his stored mask describes a formation he no longer has.
REGION_OVERRIDES = {}

def region_mask(voice):
    if voice in REGION_OVERRIDES:
        return REGION_OVERRIDES[voice]
    if voice == 'lucian':
        return np.unpackbits(reg['lucian_fill_packed'])[:H * W].reshape(H, W) > 0
    return np.unpackbits(reg['%s_packed' % KEY.get(voice, voice)])[:H * W].reshape(H, W) > 0

# ---------- build_pure rendering, verbatim ----------
def ink_layer(dens, rgb, gam, stg):
    d = np.power(np.clip(dens, 0, None), gam)
    al = 1 - np.exp(-d * 3.2 * stg)
    dn = np.clip(d, 0, 1)
    c = np.array(rgb, np.float32)[None, None, :] * (1 - 0.55 * dn[:, :, None]) + DARK[None, None, :] * (0.55 * dn[:, :, None])
    lay = np.zeros((H, W, 4), np.uint8)
    lay[..., :3] = np.clip(c, 0, 255).astype(np.uint8)
    lay[..., 3] = np.clip(al * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(lay, 'RGBA')

def fill_layer(voice):
    """build_pure's fill_layer / aria_lighten_layer, verbatim."""
    lay = np.zeros((H, W, 4), np.uint8)
    if voice == 'aria':
        lay[..., :3] = 255
        lay[..., 3] = np.clip(np.round(0.5 * region_mask('aria').astype(np.float32) * 255), 0, 255).astype(np.uint8)
    else:
        rgb = PARAMS[voice][0]
        lay[..., 0], lay[..., 1], lay[..., 2] = rgb
        lay[..., 3] = np.clip(np.round(OPACITY[voice] * region_mask(voice).astype(np.float32) * 255), 0, 255).astype(np.uint8)
    return Image.fromarray(lay, 'RGBA')

def _erode(m, iters):
    for _ in range(iters):
        m = (m & np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    return m

def aria_outline_layer():
    outline = region_mask('aria') & ~_erode(region_mask('aria').copy(), 3)
    oc = np.array(PARAMS['aria'][0], np.float32) * 0.45 + DARK * 0.55
    lay = np.zeros((H, W, 4), np.uint8)
    lay[..., :3] = np.clip(oc, 0, 255).astype(np.uint8)[None, None, :]
    lay[..., 3] = (outline * 242).astype(np.uint8)
    return Image.fromarray(lay, 'RGBA')

def resize_rgba_float(img, size, resample, absent_rgb):
    """Premultiplied resize in float32. `absent_rgb` is the colour
    written where the resized alpha is effectively zero (the
    layer's own flat colour there) — invisible by construction,
    and it keeps transparent regions compressible."""
    a = np.asarray(img).astype(np.float32)
    alpha01 = a[..., 3] / 255.0
    prem = a[..., :3] * alpha01[..., None]
    chans = [
        np.asarray(Image.fromarray(prem[..., c], mode='F').resize(size, resample))
        for c in range(3)
    ]
    A = np.asarray(Image.fromarray(a[..., 3], mode='F').resize(size, resample))
    out = np.zeros((size[1], size[0], 4), np.float32)
    present = A >= 1.0
    rgb = np.stack(chans, axis=-1) * 255.0 / np.maximum(A, 1e-9)[..., None]
    out[..., :3] = np.where(present[..., None], np.clip(rgb, 0, 255), np.array(absent_rgb, np.float32))
    out[..., 3] = np.clip(A, 0, 255)
    return Image.fromarray(np.round(out).astype(np.uint8), 'RGBA')

# ---------- per-voice ladders (density snapshots, stage 1..K) ----------
def ladder_valen():
    # build_pure's wave construction, verbatim.
    def sample(arr, xs, ys):
        xi = np.rint(xs).astype(np.int64); yi = np.rint(ys).astype(np.int64)
        ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
        o = np.zeros(xs.shape, dtype=np.float64); o[ok] = arr[yi[ok], xi[ok]].astype(np.float64)
        return o
    segs0 = []
    for i in range(6):
        a0 = math.radians(60 * i + 12); a1 = math.radians(60 * (i + 1) + 12)
        segs0.append((CX + 300.0 * math.cos(a0), CY + 300.0 * math.sin(a0),
                      CX + 300.0 * math.cos(a1), CY + 300.0 * math.sin(a1)))
    S_v = np.array(segs0, dtype=np.float64)
    for wave in range(13):
        P, Q = S_v[:, :2], S_v[:, 2:]
        mid = (P + Q) / 2
        near = sample(zero, mid[:, 0], mid[:, 1]) > 0.35
        mask = near | (wave % 3 == 2)
        U = (Q - P) / 3; P1 = P + U; P2 = P + 2 * U; M = (P1 + P2) / 2
        nx = -U[:, 1]; ny = U[:, 0]
        ln = np.hypot(nx, ny) + 1e-9; nx = nx / ln; ny = ny / ln
        flip = (nx * (M[:, 0] - CX) + ny * (M[:, 1] - CY)) < 0
        nx = np.where(flip, -nx, nx); ny = np.where(flip, -ny, ny)
        hh = np.hypot(U[:, 0], U[:, 1]) * (math.sqrt(3) / 2)
        apex = np.stack([M[:, 0] + nx * hh, M[:, 1] + ny * hh], axis=1)
        inward = sample(zero, apex[:, 0], apex[:, 1]) > 2.0
        APEX = np.stack([np.where(inward, M[:, 0] - nx * hh, apex[:, 0]),
                         np.where(inward, M[:, 1] - ny * hh, apex[:, 1])], axis=1)
        counts = np.where(mask, 4, 1); total = int(counts.sum())
        outa = np.empty((total, 4), dtype=np.float64)
        offs = np.zeros(len(S_v), dtype=np.int64); np.cumsum(counts[:-1], out=offs[1:])
        idx = np.nonzero(mask)[0]; b = offs[idx]
        outa[b] = np.concatenate([P[idx], P1[idx]], axis=1)
        outa[b + 1] = np.concatenate([P1[idx], APEX[idx]], axis=1)
        outa[b + 2] = np.concatenate([APEX[idx], P2[idx]], axis=1)
        outa[b + 3] = np.concatenate([P2[idx], Q[idx]], axis=1)
        keep = np.nonzero(~mask)[0]; outa[offs[keep]] = S_v[keep]
        S_v = outa
    n_arr = np.maximum((np.hypot(S_v[:, 2] - S_v[:, 0], S_v[:, 3] - S_v[:, 1]) / 1.1).astype(np.int64), 1)
    dens = np.zeros((H, W), np.float32)
    snaps, prev = [], 0
    for b in bounds(len(S_v)):
        fv.draw_fast(S_v[prev:b], n_arr[prev:b], dens)
        snaps.append(dens.copy()); prev = b
    return snaps, [b / len(S_v) for b in bounds(len(S_v))]

def ladder_maeve():
    # build_pure's ring_block, verbatim; rings in build order.
    def ring_block(cx, cy, r, rad, w):
        n = max(int(2 * math.pi * r / 1.1), 8)
        pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
        S, nn, rr, ww = [], [], [], []
        for p, q in zip(pts, pts[1:]):
            S.append((p[0], p[1], q[0], q[1])); nn.append(max(int(math.hypot(q[0] - p[0], q[1] - p[1]) / 1.1), 1))
            rr.append(rad); ww.append(w)
        return (np.array(S, np.float64), np.array(nn, np.int64), np.array(rr, np.float64), np.array(ww, np.float64))
    zc = np.load(IW / 'maeve_cands.npz'); cands = zc['cands']
    Cc = (750.0, 990.0); Rr = 430.0
    r_s = Rr * math.sqrt(3) / (2 + math.sqrt(3)); dd = Rr - r_s
    rings = [(Cc[0], Cc[1], Rr, 1.15 * SS, 0.9)]
    for ang in (math.radians(-90), math.radians(150), math.radians(30)):
        rings.append((Cc[0] + dd * math.cos(ang), Cc[1] + dd * math.sin(ang), r_s, 1.05 * SS, 0.85))
    for (x, y, r) in cands:
        rings.append((float(x), float(y), float(r), max(0.8 * SS * min(float(r) / 60, 1), 0.55), 0.8))
    dens = np.zeros((H, W), np.float32)
    snaps, want = [], bounds(len(rings))
    for i, ring in enumerate(rings):
        fm.draw_fast_maeve(*ring_block(*ring), dens)
        if i + 1 in want:
            snaps.append(dens.copy())
    return snaps, [b / len(rings) for b in want]

def ladder_jynx():
    zj = np.load(IW / 'jynx_full_stream.npz')
    S, n = zj['S'], zj['n']
    dens = np.zeros((H, W), np.float32)
    snaps, prev = [], 0
    for b in bounds(len(S)):
        fj.draw_fast_jynx(S[prev:b], n[prev:b], dens)
        snaps.append(dens.copy()); prev = b
    return snaps, [b / len(S) for b in bounds(len(S))]

def ladder_severine():
    # The progressive-severine instrumented runner, verbatim, against
    # zero recorded ink (the pure build: no probe ever parts).
    snap_at = set(bounds(155))
    dens = np.zeros((H, W), np.float32)
    state = {'k': 5}
    snaps = {}
    count = {'n': 0}
    def seg(p, q):
        n = max(int(math.hypot(q[0] - p[0], q[1] - p[1]) / 1.1), 1)
        for i in range(n + 1):
            state['k'] += 1
            if state['k'] % 6 >= 4: continue
            x = p[0] + (q[0] - p[0]) * i / n; y = p[1] + (q[1] - p[1]) * i / n
            if at(zero, x, y) > 3.2: continue
            j = (((state['k'] * 2654435761) >> 9) % 100 / 100.0 - 0.5) * 1.6
            splat(dens, x + j, y + j * 0.6, 0.7 * SS, 0.72)
    def square(cx, cy, s):
        h = s / 2
        pts = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h), (cx - h, cy - h)]
        for p, q in zip(pts, pts[1:]): seg(p, q)
        count['n'] += 1
        if count['n'] in snap_at:
            snaps[count['n']] = dens.copy()
    def probe(cx, cy, s, depth, outermost=False):
        if not outermost: square(cx, cy, s)
        if depth == 0: return
        t = s / 3
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                if (ddx, ddy) in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)):
                    probe(cx + ddx * t, cy + ddy * t, t, depth - 1)
    probe(750.0, 990.0, 660.0, 3, outermost=True)
    assert count['n'] == 155, count['n']
    ordered = [snaps[b] for b in bounds(155)]
    return ordered, [b / 155 for b in bounds(155)]

def ladder_aria():
    # build_pure's Julia loop, verbatim, with per-iteration snapshots.
    HALF = 660; SCALE = 400.0
    xs = (np.arange(CX - HALF, CX + HALF) - CX) / SCALE
    ys = (CY - np.arange(CY - HALF, CY + HALF)) / SCALE
    X, Y = np.meshgrid(xs, ys)
    z = (X + 1j * Y).astype(np.complex128); dz = np.ones_like(z)
    esc = np.zeros(z.shape, bool); dist = np.full(z.shape, 1e9)
    snap_at = bounds(150)
    snaps = []
    def band_now():
        band = np.clip(1.0 - (dist * SCALE) / 3.0, 0.0, 1.0); band[esc == False] = 0.0
        full = np.zeros((H, W), np.float32)
        crop = np.s_[int(CY - HALF):int(CY + HALF), int(CX - HALF):int(CX + HALF)]
        full[crop] = (band * 1.0 * 1.4).astype(np.float32)
        return full
    done = False
    for it in range(150):
        if not done:
            live = ~esc
            if not live.any():
                done = True
            else:
                dz[live] = 2.0 * z[live] * dz[live]
                z[live] = z[live] * z[live] + (-0.8 + 0.156j)
                big = live & (np.abs(z) > 256.0)
                if big.any():
                    az = np.abs(z[big]); adz = np.abs(dz[big])
                    dist[big] = 0.5 * az * np.log(az) / np.maximum(adz, 1e-12)
                    esc |= big
        if it + 1 in snap_at:
            snaps.append(band_now())
    return snaps, [b / 150 for b in snap_at]

def _study():
    return load_mod('directional_study', STUDY / 'build_directional_study.py')

def ladder_rumi():
    # Cardinals only (founder ruling 2026-11-25 — see the module
    # docstring). The diagonal specs survive in
    # verify_rumi_cardinals.py, which re-proves the recomposition
    # anchor against the superseded canonical geometry.
    # Snapshots are taken every round (snap_every=1) so the 12
    # sampled stage fractions track the uniform grid within the
    # pinned 0.01 tolerance; snapshot density does not change the
    # growth — the final snapshot is the completed formation
    # either way (measured: snap_every=2 samples deviate 0.0119,
    # snap_every=1 samples 0.0088).
    ds = _study()
    card_specs = [(ds.CX, ds.CY, -1.57, 58, 1.35, 0.002, 101),
                  (ds.CX, ds.CY, -1.22, 44, 1.1, 0.008, 102),
                  (ds.CX, ds.CY, -1.92, 44, 1.1, -0.008, 103)]
    card_raw, card_snaps, _ = ds.grow_fern_fan(card_specs, snap_every=1)
    card_final = ds.compose4(card_raw)
    seq = [ds.compose4(s) for s in card_snaps]
    if sha(seq[-1]) != sha(card_final):
        seq[-1] = card_final
    idx = [int(round(j * (len(seq) - 1) / K)) for j in range(1, K + 1)]
    return [seq[i] for i in idx], [i / (len(seq) - 1) for i in idx], seq

def ladder_lucian():
    ds = _study()
    card_raw, card_snaps, _, _ = ds.grow_channels((ds.CX, ds.CY - ds.R_CIRCLE), math.pi / 2, 201, 78, snap_every=3)
    card_final = ds.compose4(card_raw)
    diag_raw, diag_snaps, _, _ = ds.grow_channels((ds.CX, ds.CY), math.radians(-45), 211, 31, snap_every=2, shrink=0.45, fork_p=0.18)
    final = np.maximum(card_final, ds.compose4(diag_raw))
    seq = [ds.compose4(s) for s in card_snaps] + [np.maximum(card_final, ds.compose4(s)) for s in diag_snaps]
    if sha(seq[-1]) != sha(final):
        seq[-1] = final
    idx = [int(round(j * (len(seq) - 1) / K)) for j in range(1, K + 1)]
    return [seq[i] for i in idx], [i / (len(seq) - 1) for i in idx], seq

LADDERS = {'valen': ladder_valen, 'maeve': ladder_maeve, 'jynx': ladder_jynx,
           'severine': ladder_severine, 'aria': ladder_aria,
           'rumi': ladder_rumi, 'lucian': ladder_lucian}

# ---------- metrics ----------
def img_diff(a_img, b_img):
    a = np.asarray(a_img).astype(np.int32); b = np.asarray(b_img).astype(np.int32)
    d = np.abs(a - b)
    strong = np.asarray(b_img)[..., 3] > 128  # shipped ink strong territory
    sup_a = np.asarray(a_img)[..., 3] > 8; sup_b = np.asarray(b_img)[..., 3] > 8
    return {
        'meanAbsDiff': round(float(d.mean()), 3),
        'alphaMeanAbsDiff': round(float(d[..., 3].mean()), 3),
        'pctPxOver8': round(float((d.max(axis=2) > 8).mean() * 100), 3),
        'strongInkMeanAbsDiff': round(float(d[strong].mean()), 3) if strong.any() else None,
        'supportIou': round(float((sup_a & sup_b).sum() / max((sup_a | sup_b).sum(), 1)), 4),
    }

def over(top, bot):
    t = np.asarray(top).astype(np.float32) / 255; b = np.asarray(bot).astype(np.float32) / 255
    a = t[..., 3:4] + b[..., 3:4] * (1 - t[..., 3:4])
    rgb = (t[..., :3] * t[..., 3:4] + b[..., :3] * b[..., 3:4] * (1 - t[..., 3:4])) / np.maximum(a, 1e-9)
    out = np.zeros((*a.shape[:2], 4), np.uint8)
    out[..., :3] = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(a[..., 0] * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')

# ---------- main ----------
def main():
    only = None
    if '--voice' in sys.argv:
        only = sys.argv[sys.argv.index('--voice') + 1]
        if only not in VOICES:
            raise SystemExit('unknown voice: %s' % only)
    manifest_path = ATELIER / 'stage-manifest.json'
    if only:
        # Single-voice regeneration: the recorded entries for the
        # other voices (and the historical previous* totals) are
        # preserved exactly; only this voice's entry is recomputed.
        manifest = json.loads(manifest_path.read_text())
        prev_ink_bytes = manifest['totals']['previousInkBytes']
        prev_fill_bytes = manifest['totals']['previousFillBytes']
    else:
        manifest = {
            'generatedBy': 'frontend/src/aria-atelier/stagegen/generate_stages.py',
            'stagesPerVoice': K,
            'intermediateSize': list(MID_SIZE),
            'finalSize': list(FINAL_SIZE),
            'voices': {},
            'totals': {},
        }
        prev_ink_bytes = None  # measured from the shipped splits below
        # The shipped fills are overwritten in place by this script,
        # so their original sizes are the recorded constant (measured
        # 2026-11-25: aria 11068, jynx 26107, lucian 28427, maeve
        # 13400, rumi 17706, severine 12811, valen 9631).
        prev_fill_bytes = 119150
    shipped_ink_bytes = 0
    for voice in ([only] if only else VOICES):
        log('== %s ==' % voice)
        key = KEY.get(voice, voice)
        ink_split = ASSETS / ('layer-%s-ink.png' % voice)
        if ink_split.exists():
            shipped_ink = Image.open(ink_split).convert('RGBA')
            shipped_ink_bytes += ink_split.stat().st_size
            ink_ref_kind = 'shipped split (layer-%s-ink.png)' % voice
        else:
            # PR #434 deleted the #414 ink splits in the same commit
            # that added this script, so on current main the Gate-4
            # reference is the canonical ink render: build_pure's
            # layer construction (ink_layer at full resolution, PIL
            # Lanczos resize) of the final density — the construction
            # that produced the canonical layer-<voice>.png exports.
            # Rendered after the ladder, below.
            shipped_ink = None
            ink_ref_kind = 'canonical ink render (ink splits deleted by PR #434)'
        out = LADDERS[voice]()
        snaps, fractions = out[0], out[1]
        full_seq = out[2] if len(out) > 2 else snaps
        assert len(snaps) == K, (voice, len(snaps))
        # Gate 1: the final density IS the canonical geometry.
        expected_sha = expected_canonical_sha(voice, key)
        final_sha = sha(snaps[-1])
        gate = final_sha == expected_sha
        log('%s final density sha %s == canonical %s : %s' % (voice, final_sha[:12], expected_sha[:12], gate))
        if not gate:
            raise SystemExit('GATE FAIL: %s final density does not reproduce the canonical geometry' % voice)
        if voice == 'rumi':
            # His fill washes the regions his REMAINING ink
            # encloses: recompute the region mask from the new
            # density with build_pure's own region code (shape_of,
            # verbatim). verify_rumi_cardinals.py re-proves that
            # the same code on the superseded density reproduces
            # regions-pure's stored rumi mask bit-exactly.
            REGION_OVERRIDES['rumi'] = shape_of(snaps[-1], PARAMS['rumi'][1])
            stored_rumi = np.unpackbits(reg['rumi_packed'])[:H * W].reshape(H, W) > 0
            log('rumi region recomputed from the cardinals-only density: %d px (superseded mask: %d px)' % (
                int(REGION_OVERRIDES['rumi'].sum()), int(stored_rumi.sum())))
        # Gate 2: prefix truth on densities — every stage a subset of
        # the next (elementwise, over the full sequence where the
        # growth machinery provides one).
        mono = True
        chain = full_seq if len(full_seq) >= len(snaps) else snaps
        for a, b in zip(chain, chain[1:]):
            if not bool(np.all(b >= a)):
                mono = False
        for a, b in zip(snaps, snaps[1:]):
            if not bool(np.all(b >= a)):
                mono = False
        log('%s density ladder monotone: %s (chain of %d)' % (voice, mono, len(chain)))
        if not mono:
            raise SystemExit('GATE FAIL: %s density ladder is not a true prefix chain' % voice)
        # Render stages. Intermediates are bilinear (positive
        # weights — the rendered ladder stays exactly monotone);
        # the final is Lanczos, as build_pure made the shipped
        # layers. The monotonicity check ladder is taken from the
        # full-res renders through the same bilinear path.
        rgb, gam, stg = PARAMS[voice]
        stage_files = []
        rendered_small = []
        for j, dens in enumerate(snaps, start=1):
            img = ink_layer(dens, rgb, gam, stg)
            if voice == 'aria' and j == K:
                img.alpha_composite(aria_outline_layer())
            small = resize_rgba_float(img, MID_SIZE, Image.BILINEAR, (0, 0, 0))
            rendered_small.append(np.asarray(small)[..., 3].astype(np.int32))
            out_img = resize_rgba_float(img, FINAL_SIZE, Image.LANCZOS, (0, 0, 0)) if j == K else small
            path = STAGES_DIR / ('stage-%s-%d.png' % (voice, j))
            out_img.save(path, compress_level=9)
            stage_files.append(path.stat().st_size)
        # Gate 3: rendered alpha ladder — max pointwise decrease
        # between consecutive stages (Lanczos may ring by a level
        # or two; a true decrease would break prefix truth).
        max_dec = 0
        for a, b in zip(rendered_small, rendered_small[1:]):
            max_dec = max(max_dec, int((a - b).max()))
        log('%s rendered alpha max decrease between stages: %d' % (voice, max_dec))
        # Regenerate the fill split (build_pure construction).
        fill_absent = (255, 255, 255) if voice == 'aria' else PARAMS[voice][0]
        fill_img = resize_rgba_float(fill_layer(voice), FINAL_SIZE, Image.LANCZOS, fill_absent)
        fill_path = ASSETS / ('layer-%s-fill.png' % voice)
        fill_img.save(fill_path, compress_level=9)
        # Gate 4: final stage vs the shipped ink split, and the
        # composed final vs the canonical layer export.
        final_img = Image.open(STAGES_DIR / ('stage-%s-%d.png' % (voice, K))).convert('RGBA')
        if shipped_ink is None:
            rgb_c, gam_c, stg_c = PARAMS[voice]
            shipped_ink = ink_layer(snaps[-1], rgb_c, gam_c, stg_c).resize(FINAL_SIZE, Image.LANCZOS)
        vs_shipped = img_diff(final_img, shipped_ink)
        if voice == 'rumi':
            # The layer export in atelier-timing predates the
            # 2026-11-25 ruling; Rumi's canonical layer is now the
            # build_pure construction over the recomputed region:
            # the fill layer alpha-composited with the ink layer at
            # full resolution, PIL Lanczos resize — the same
            # construction that produced layer-rumi.png in its day.
            canon_layer = fill_layer(voice)
            canon_layer.alpha_composite(ink_layer(snaps[-1], rgb_c, gam_c, stg_c))
            canon_layer = canon_layer.resize(FINAL_SIZE, Image.LANCZOS)
        else:
            canon_layer = Image.open(PURE / ('layer-%s.png' % voice)).convert('RGBA')
        composed = over(final_img, fill_img)
        vs_canon = float(np.abs(np.asarray(composed).astype(np.int32) - np.asarray(canon_layer).astype(np.int32)).mean())
        log('%s final vs shipped ink: %s | composed vs canonical layer mean %.3f' % (voice, vs_shipped, vs_canon))
        manifest['voices'][voice] = {
            'finalDensitySha256': final_sha,
            'canonicalDensitySha256': expected_sha,
            'finalDensityMatchesCanonical': gate,
            'densityLadderMonotone': mono,
            'renderedAlphaMaxDecrease': max_dec,
            'stageFractions': [round(f, 4) for f in fractions],
            'finalVsShippedInk': vs_shipped,
            'finalVsShippedInkReference': ink_ref_kind,
            'finalCompositeVsCanonicalLayerMeanAbsDiff': round(vs_canon, 3),
            'stageBytes': stage_files,
            'fillBytes': fill_path.stat().st_size,
        }
        if voice == 'rumi':
            manifest['voices'][voice]['supersededCanonicalDensitySha256'] = HASHES['rumi']
            manifest['voices'][voice]['canonicalNote'] = (
                'Founder ruling 2026-11-25: cardinals only — the rim-rooted inward '
                'diagonal family is removed from Rumi (Lucian untouched). Region '
                'mask recomputed from the new density by build_pure shape_of; '
                'anchors re-provable via stagegen/verify_rumi_cardinals.py.')
        manifest_path.write_text(json.dumps(manifest, indent=1))
    # Totals are recomputed from the per-voice records; any other
    # keys already recorded in totals (e.g. a twinBytes entry from
    # the dynamism build) are preserved, not clobbered.
    totals = dict(manifest.get('totals') or {})
    totals.update({
        'stageBytes': sum(sum(v['stageBytes']) for v in manifest['voices'].values()),
        'fillBytes': sum(v['fillBytes'] for v in manifest['voices'].values()),
        'previousInkBytes': prev_ink_bytes if prev_ink_bytes is not None else shipped_ink_bytes,
        'previousFillBytes': prev_fill_bytes,
    })
    manifest['totals'] = totals
    manifest['resampling'] = {'intermediate': 'float-premultiplied bilinear', 'final': 'float-premultiplied lanczos'}
    manifest_path.write_text(json.dumps(manifest, indent=1))
    if only:
        log('DONE in %.1fs — single voice %s regenerated; other voices preserved' % (time.time() - T0, only))
        return
    # stageImages.ts — explicit generated imports.
    lines = [
        '/**',
        ' * GENERATED by stagegen/generate_stages.py — do not edit by hand.',
        ' *',
        ' * The Well\'s true-prefix formation ladders: stage j of a voice',
        ' * is its canonical geometry drawn to stage j\'s recorded fraction',
        ' * of its growth (see stage-manifest.json for the verification',
        ' * record and each stage\'s exact fraction). Index 0 in each list',
        ' * is stage 1; the last entry is the completed formation.',
        ' */',
        "import type { Voice } from './atelierLogic'",
        '',
    ]
    for voice in VOICES:
        for j in range(1, K + 1):
            lines.append("import %s%d from './assets/stages/stage-%s-%d.png'" % (voice, j, voice, j))
    lines.append('')
    lines.append('export const STAGE_IMAGES: Record<Voice, readonly string[]> = {')
    for voice in VOICES:
        lines.append('  %s: [%s],' % (voice, ', '.join('%s%d' % (voice, j) for j in range(1, K + 1))))
    lines.append('}')
    lines.append('')
    (ATELIER / 'stageImages.ts').write_text('\n'.join(lines))
    log('DONE in %.1fs — stage bytes %d, previous ink bytes %d' % (
        time.time() - T0, manifest['totals']['stageBytes'], manifest['totals']['previousInkBytes']))

if __name__ == '__main__':
    main()
