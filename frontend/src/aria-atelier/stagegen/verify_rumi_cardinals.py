#!/usr/bin/env python3
"""Rumi cardinals-only — the anchor proofs, re-runnable.

Founder ruling 2026-11-25: Rumi's canonical Atelier formation is
his cardinals only; the rim-rooted inward diagonal family is
removed. This script re-proves, from the canonical sources, that
the new canonical is the old one minus exactly that family —
grown and rendered by the canonical machinery, never redrawn:

  A  recomposition: grow the cardinal family and the diagonal
     family with the directional study's own machinery
     (grow_fern_fan + compose4, the study's exact specs) and take
     np.maximum — the result is BIT-EXACTLY geometry-pure.npz's
     rumi array, the superseded canonical geometry.
  B  identity: the cardinals-only density's sha256 is the pinned
     RUMI_CARDINALS_ONLY_SHA256 in generate_stages.py and the
     finalDensitySha256 recorded for rumi in stage-manifest.json.
  C  region faithfulness: build_pure's region code (shape_of)
     run on the SUPERSEDED density reproduces regions-pure.npz's
     stored rumi mask BIT-EXACTLY — so the same code run on the
     new density (which is how the shipped fill was made) is the
     canonical region machinery, not an approximation.
  D  shipped stage 12: pixel-identical (and byte-identical) to
     generate_stages' own render of the new density — ink_layer
     through the float-premultiplied Lanczos path.
  E  shipped fill: pixel-identical (and byte-identical) to
     generate_stages' fill construction over the region mask
     recomputed from the new density.

Run: python3 verify_rumi_cardinals.py     (exit 1 on any failure)
"""
import hashlib, importlib.util, io, json, math, pathlib, sys
import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ATELIER = HERE.parent
PURE = pathlib.Path.home() / 'workspace/atelier-timing/pure-composite'

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

gs = load_mod('generate_stages', HERE / 'generate_stages.py')
ds = gs._study()

FAILURES = []

def check(name, ok, detail):
    print('%-4s %-28s %s' % ('PASS' if ok else 'FAIL', name, detail), flush=True)
    if not ok:
        FAILURES.append(name)

def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

# ---------- the two families, the study's exact specs ----------
CX, CY = ds.CX, ds.CY
card_specs = [(CX, CY, -1.57, 58, 1.35, 0.002, 101),
              (CX, CY, -1.22, 44, 1.1, 0.008, 102),
              (CX, CY, -1.92, 44, 1.1, -0.008, 103)]
ang = math.radians(-45)
rx, ry = CX + ds.R_CIRCLE * math.cos(ang), CY + ds.R_CIRCLE * math.sin(ang)
axis = math.atan2(CY - ry, CX - rx)
diag_specs = [(rx, ry, axis, 32, 1.35, 0.002, 111),
              (rx, ry, axis + 0.35, 24, 1.1, 0.008, 112),
              (rx, ry, axis - 0.35, 24, 1.1, -0.008, 113)]

card_final = ds.compose4(ds.grow_fern_fan(card_specs, snap_every=2)[0])
diag_final = ds.compose4(ds.grow_fern_fan(diag_specs, snap_every=2)[0])
full = np.maximum(card_final, diag_final)

geo = np.load(PURE / 'geometry-pure.npz')
superseded = geo['rumi']

# ---------- A: recomposition is the superseded canonical ----------
check('A recomposition bit-exact',
      bool(np.array_equal(full, superseded)),
      'max|diff| = %g over %d px' % (float(np.abs(full - superseded).max()), full.size))

# ---------- B: the cardinals-only identity ----------
manifest = json.loads((ATELIER / 'stage-manifest.json').read_text())
check('B cardinals-only sha',
      sha(card_final) == gs.RUMI_CARDINALS_ONLY_SHA256 == manifest['voices']['rumi']['finalDensitySha256'],
      'sha256 %s' % sha(card_final))

# ---------- C: region machinery faithful on the superseded density ----------
reg = np.load(PURE / 'regions-pure.npz')
H, W = superseded.shape
stored_mask = np.unpackbits(reg['rumi_packed'])[:H * W].reshape(H, W) > 0
recomputed_mask = gs.shape_of(superseded, gs.PARAMS['rumi'][1])
check('C region machinery bit-exact',
      bool(np.array_equal(recomputed_mask, stored_mask)),
      '%d px, identical' % int(stored_mask.sum()))

# ---------- D: shipped stage 12 is the stagegen render ----------
rgb, gam, stg = gs.PARAMS['rumi']
rendered12 = gs.resize_rgba_float(gs.ink_layer(card_final, rgb, gam, stg),
                                  gs.FINAL_SIZE, Image.LANCZOS, (0, 0, 0))
stage12_path = ATELIER / 'assets/stages/stage-rumi-12.png'
buf = io.BytesIO()
rendered12.save(buf, format='PNG', compress_level=9)
check('D stage 12 pixel-identical',
      bool(np.array_equal(np.asarray(rendered12), np.asarray(Image.open(stage12_path).convert('RGBA')))),
      'byte-identical: %s' % (buf.getvalue() == stage12_path.read_bytes()))

# ---------- E: shipped fill is the fill construction over the recomputed region ----------
gs.REGION_OVERRIDES['rumi'] = gs.shape_of(card_final, gam)
rendered_fill = gs.resize_rgba_float(gs.fill_layer('rumi'), gs.FINAL_SIZE,
                                     Image.LANCZOS, gs.PARAMS['rumi'][0])
fill_path = ATELIER / 'assets/layer-rumi-fill.png'
buf = io.BytesIO()
rendered_fill.save(buf, format='PNG', compress_level=9)
check('E fill pixel-identical',
      bool(np.array_equal(np.asarray(rendered_fill), np.asarray(Image.open(fill_path).convert('RGBA')))),
      'byte-identical: %s | region %d px (superseded %d px)' % (
          buf.getvalue() == fill_path.read_bytes(),
          int(gs.REGION_OVERRIDES['rumi'].sum()), int(stored_mask.sum())))

if FAILURES:
    print('FAILED: %s' % ', '.join(FAILURES))
    sys.exit(1)
print('ALL ANCHORS HOLD')
