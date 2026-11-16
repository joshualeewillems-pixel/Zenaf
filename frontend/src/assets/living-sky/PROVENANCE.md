# Living Sky scene assets — provenance

Shipped WebP conversions of the accepted Living Sky study assets
(founder acceptance 2026-11-16 02:05 PT; port plan
`zenaf-living-sky-port-plan-2026-11-16.md` §6). Converted once with PIL
at native resolution; do not re-derive from the study page (it inlines
base64 — these files are the shipped form).

| Shipped file | Study source | WebP quality | Bytes |
|---|---|---:|---:|
| `plate.webp` | `rendering-test-assets/world-plate/founder-world-plate-v2-2x3-2026-11-14.jpg` | q80 | 336,666 |
| `canopy-back.webp` | `rendering-test-assets/world-sky/canopy-back.png` | q82 | 248,798 |
| `canopy-fore.webp` | `rendering-test-assets/world-sky/canopy-fore.png` | q82 | 206,592 |
| `tree-painted.webp` | `rendering-test-assets/world-sky/tree-painted.png` | q85 | 100,300 |
| `glow-colour.webp` | `rendering-test-assets/world-sky/glow-colour.png` | q80 | 67,412 |
| `glow-white.webp` | `rendering-test-assets/world-sky/glow-white.png` | q80 | 64,676 |
| `enso-sun.webp` | `rendering-test-assets/world-sky/enso-sun-v3.png` (the founder's own ensō painting, crop/pad/resize only) | q88 | 68,040 |
| `enso-moon.webp` | `rendering-test-assets/world-sky/enso-moon.png` (the sun painting flipped, red keyed out) | q88 | 48,704 |
| `moon-face.webp` | `rendering-test-assets/world-sky/moon-face.png` (lavender face sampled from the founder's reference photo) | q85 | 20,076 |
| `wash-dawn.webp` | `rendering-test-assets/world-sky/wash-dawn.jpg` (pre-rendered ink wash, dawn/dusk) | q80 | 40,352 |

Total shipped image payload: 1,201,616 bytes.

Notes:
- The paper-moon variant (`moon-face-paper.png` in the study folder) is
  deliberately NOT ported — built 2026-11-16 01:03 PT, reverted by the
  founder 01:11 PT ("purple was better").
- The painted tree layers are 800×1320 (2× the 400×660 scene frame);
  the ensō assets are 480×480 displayed at 126/62 units; the moon face
  is 600×600 displayed at 40 local units (×1.5 wrapper).
- Sky data (stars, constellation lines, mountain silhouette path) lives
  with the code in `frontend/src/living-tree/sky-data/`, copied verbatim
  from `rendering-test-assets/world-sky/{stars-compact,lines-compact,sky-path}.json`.
