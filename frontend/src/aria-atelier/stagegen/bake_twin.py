#!/usr/bin/env python3
"""Bake a refraction twin — the Atelier dynamism pass (spec §2.3).

A twin is a blurred, half-resolution copy of one stage image,
rendered beneath that stage's ink in the cast view so the ink
reads as lying IN the water rather than on it. The founder's
review (2026-11-25) gated this mechanism to ONE representative
twin, judged on the actual water before any batch exists: a
blurred underlay can read as shadow, ghost, or registration
error rather than refraction, and 84 assets are an architectural
cost, not just a computational one. The batch, if the verdict
earns it, is this same bake with TWINS extended — nothing else
about the pipeline changes.

The prototype twin is LUCIAN, stage 6 — exactly mid-ladder. His
dendritic channel network is the densest continuous ink of the
seven voices, so a blur survives the half-resolution downscale
as a legible smear; Jynx, the other candidate, draws 1–2px
Penrose lines that a blur + downscale would largely erase (the
#434 report flags the same thin-line resampling fragility),
making him a test of absence rather than of refraction.

Method (the stagegen discipline — float premultiplied space
throughout, as generate_stages.py's resizes):
  1. gaussian blur at ASSET resolution: separable kernel,
     sigma = 1.0 (FWHM ≈ 2.4px — the spec's "~2px"), applied to
     the premultiplied channels with reflect padding;
  2. half-resolution downscale through the float-premultiplied
     bilinear path (generate_stages.resize_rgba_float's method,
     in miniature);
  3. absent colour where alpha is effectively zero is the ink's
     own: black, as the stage PNGs carry it.

Outputs:
  assets/stages/stage-<voice>-<n>-refr.png   (the twin)
  stage-manifest.json                        (gains a `twins`
     record + totals.twinBytes; every existing record untouched)

Run: python3 bake_twin.py            (from anywhere)
"""
import json, pathlib
import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ATELIER = HERE.parent
STAGES_DIR = ATELIER / 'assets' / 'stages'

# The prototype set: ONE twin (founder's gate, 2026-11-25).
TWINS = [('lucian', 6)]

BLUR_SIGMA = 1.0


def gaussian_kernel(sigma):
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2 * sigma * sigma))
    return k / k.sum()


def blur_axis(a, kernel, axis):
    radius = len(kernel) // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(a, pad, mode='reflect')
    out = np.zeros_like(a)
    for i, w in enumerate(kernel):
        sl = [slice(None)] * a.ndim
        sl[axis] = slice(i, i + a.shape[axis])
        out += padded[tuple(sl)] * w
    return out


def premultiplied(img):
    a = np.asarray(img).astype(np.float32)
    alpha01 = a[..., 3] / 255.0
    prem = a[..., :3] * alpha01[..., None]
    return prem, a[..., 3]


def unpremultiplied(prem, alpha, absent_rgb=(0, 0, 0)):
    out = np.zeros((*alpha.shape, 4), np.float32)
    present = alpha >= 1.0
    rgb = prem * 255.0 / np.maximum(alpha, 1e-9)[..., None]
    out[..., :3] = np.where(present[..., None], np.clip(rgb, 0, 255),
                            np.array(absent_rgb, np.float32))
    out[..., 3] = np.clip(alpha, 0, 255)
    return Image.fromarray(np.round(out).astype(np.uint8), 'RGBA')


def resize_half_bilinear(prem, alpha):
    """Float-premultiplied bilinear downscale to half size —
    generate_stages.resize_rgba_float's method at factor 2."""
    h, w = alpha.shape
    size = (w // 2, h // 2)
    chans = [
        np.asarray(Image.fromarray(prem[..., c], mode='F').resize(size, Image.BILINEAR))
        for c in range(3)
    ]
    A = np.asarray(Image.fromarray(alpha, mode='F').resize(size, Image.BILINEAR))
    return np.stack(chans, axis=-1), A


def bake(voice, stage):
    src_path = STAGES_DIR / ('stage-%s-%d.png' % (voice, stage))
    img = Image.open(src_path).convert('RGBA')
    prem, alpha = premultiplied(img)
    kernel = gaussian_kernel(BLUR_SIGMA)
    blurred_prem = prem
    for axis in (0, 1):
        blurred_prem = blur_axis(blurred_prem, kernel, axis)
    blurred_alpha = alpha
    for axis in (0, 1):
        blurred_alpha = blur_axis(blurred_alpha, kernel, axis)
    small_prem, small_alpha = resize_half_bilinear(blurred_prem, blurred_alpha)
    twin = unpremultiplied(small_prem, small_alpha)
    out_path = STAGES_DIR / ('stage-%s-%d-refr.png' % (voice, stage))
    twin.save(out_path, compress_level=9)
    return {
        'voice': voice,
        'stage': stage,
        'file': out_path.name,
        'size': list(twin.size),
        'bytes': out_path.stat().st_size,
        'sourceBytes': src_path.stat().st_size,
        'method': 'gaussian blur sigma=%.1f at asset resolution, float premultiplied; '
                  'half-resolution float-premultiplied bilinear' % BLUR_SIGMA,
    }


def main():
    records = [bake(voice, stage) for voice, stage in TWINS]
    manifest_path = ATELIER / 'stage-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['twins'] = records
    manifest.setdefault('totals', {})['twinBytes'] = sum(r['bytes'] for r in records)
    manifest_path.write_text(json.dumps(manifest, indent=1))
    for r in records:
        print('twin: %s — %dx%d, %d bytes (source %d bytes)' % (
            r['file'], r['size'][0], r['size'][1], r['bytes'], r['sourceBytes']))


if __name__ == '__main__':
    main()
