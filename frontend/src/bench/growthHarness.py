"""Port-equivalence harness for Severine's Bench growth machinery.

Deals two trees from the frozen Palace-study fixture (sha256
6a85e7f82657bda28d7dd785b138d8cad5ea78422cd3e33772f10bf7d2753949)
into growth elements under the dealing rules documented below, grows
them with the CANONICAL Python machinery (growth_demo3.grow /
trunk_point / cluster_pads, imported — never reimplemented here), and
dumps the geometry as JSON. The TypeScript port
(frontend/src/bench/growth.ts) must reproduce this geometry point for
point from the same element table; growth.test.ts performs the
comparison.

Dealing rules (the same rules benchLogic.ts applies to product data,
specialised to the fixture's fields):
- One element per branch (a project's rooms + annex steps, in record
  order).
- Geometry register: 'wire' when the branch carries a recorded
  proposal (the fixture's two wired branches are dealt from the
  accepted prototype's data: B1-T2 and B2-T2); else 'ink' for
  Done / In Progress ("in-hand"); else 'pencil'.
- Strand weight from state: Done 8, In Progress 6, Todo 4, Parked 3.
  (Matches the weights the accepted prototype dealt B1/B2.)
- Length = 46 + weight * 15.
- Sides alternate in record order, starting left (-1). Stations: per
  side, spread evenly t = 0.16 .. 0.88 (a lone branch sits at 0.5).
- Elevation = 16 + weight * 2.2 (grow_forest clamps to 12..44).
- Sprite 1 for every element (one species on the Bench; the seat tint
  leans the cherry family, per growth_demo3.seat_tint).
- Crosses (bridge pads): fixture dependency edges whose endpoints are
  both branches of the same tree (B1: B1-T3 -> B1-T1).
- Voids: none. The demo's voids belong to its passage data; the
  fixture records no held voids, and the product deals none either.

Run: python3 growthHarness.py   (writes __fixtures__/growth-fixture.json)
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
STAGE1A = pathlib.Path.home() / "workspace/rendering-test-assets/bonsai-stage1a"
FIXTURE = (
    pathlib.Path.home()
    / "workspace/rendering-test-assets/maeve-palace-study/fixture.json"
)
sys.path.insert(0, str(STAGE1A))

import growth_demo3 as gd  # noqa: E402
from stills_v2 import seed_rng  # noqa: E402

# The fixture deals no held voids (see module docstring).
gd.VOIDS = []

WIRED = {"B1-T2", "B2-T2"}  # branches carrying a recorded proposal
WEIGHT_BY_STATE = {"Done": 8, "In Progress": 6, "Todo": 4, "Parked": 3}


def deal(project: dict, edges: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    branches: list[dict] = []
    for room in project.get("rooms", []):
        branches.append({"id": room["id"], "state": room["state"]})
    for step in project.get("annex_steps", []):
        branches.append(
            {
                "id": f"{project['id']}-{step['name']}",
                "state": "Done" if step.get("done") else "Todo",
            }
        )
    # Stable ids for annex steps in the prototype were B1-a/B1-b/B1-c in
    # record order; rename positionally so handles match the prototype.
    letters = "abcdefghijklmnopqrstuvwxyz"
    ai = 0
    for b in branches:
        if "-" in b["id"] and b["id"].split("-", 1)[1][0].isalpha() and " " in b["id"]:
            b["id"] = f"{project['id']}-{letters[ai]}"
            ai += 1
    by_side: dict[int, list[dict]] = {-1: [], 1: []}
    elements: list[dict] = []
    for i, b in enumerate(branches):
        side = -1 if i % 2 == 0 else 1
        by_side[side].append(b)
        weight = WEIGHT_BY_STATE.get(b["state"], 4)
        register = (
            "wire" if b["id"] in WIRED else "ink" if b["state"] in ("Done", "In Progress") else "pencil"
        )
        elements.append(
            dict(
                handle=b["id"],
                register=register,
                side=side,
                weight=weight,
                len_old=46.0 + weight * 15.0,
                elev=16.0 + weight * 2.2,
                sprite=1,
            )
        )
    for side, bs in by_side.items():
        m = len(bs)
        for j, b in enumerate(bs):
            t = 0.5 if m == 1 else 0.16 + 0.72 * (j / (m - 1))
            for el in elements:
                if el["handle"] == b["id"]:
                    el["t_grow"] = t
    ids = {b["id"] for b in branches}
    crosses = [
        (e["from"], e["to"])
        for e in edges
        if e.get("kind") == "dependency" and e.get("from") in ids and e.get("to") in ids
    ]
    return elements, crosses


def grow_tree(elements: list[dict], crosses: list[tuple[str, str]]) -> dict:
    gd.WOOD.clear()
    gd.TWIGS.clear()
    gd.ANCHORS.clear()
    gd.STATS.clear()
    gd.CROSS_PARTNER.clear()
    for a, b in crosses:
        gd.CROSS_PARTNER[a] = b
        gd.CROSS_PARTNER[b] = a
    primaries: dict[str, list] = {}
    for el in elements:
        gd.ANCHORS[el["handle"]] = []
        rng = seed_rng("grammar5", el["handle"])
        start, _tan = gd.trunk_point(el["t_grow"])
        elev = max(12.0, min(44.0, el["elev"]))
        phi = elev if el["side"] > 0 else 180.0 - elev
        if el["handle"] in gd.CROSS_PARTNER:
            phi += 5.0 * (1 if phi < 90 else -1)
        length = el["len_old"] * gd.PARAMS["len_scale"][el["register"]]
        pts = gd.grow(start, phi, length, 0, el, rng, gd.PARAMS)
        primaries[el["handle"]] = pts
        w = gd.PARAMS["wood_w"][el["register"]]
        gd.WOOD.append((pts, w, 0.7, 0, el))
    # apex shoot, as grow_forest grows it
    gd.ANCHORS["apex"] = []
    tip, tan = gd.trunk_point(1.0)
    el_apex = dict(handle="apex", register="pencil")
    rng = seed_rng("grammar5", "apex")
    phi_apex = math.degrees(math.atan2(-tan[1], tan[0]))
    pts = gd.grow(tip, phi_apex, 34.0, 1, el_apex, rng, gd.PARAMS, record=False)
    gd.WOOD.append((pts, 1.6, 0.4, 1, el_apex))

    pads_by: dict[str, list] = {}
    for el in elements:
        pads = gd.cluster_pads(el["handle"], gd.ANCHORS[el["handle"]], gd.PARAMS)
        pads_by[el["handle"]] = [p for p in pads if not gd.in_void(p["c"][0], p["c"][1], 1.0)]
    if gd.ANCHORS.get("apex"):
        pads_by["apex"] = gd.cluster_pads("apex", gd.ANCHORS["apex"], gd.PARAMS)
    bridges = []
    seen: set = set()
    for a, b in crosses:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        pa, pb = pads_by.get(a, []), pads_by.get(b, [])
        if not pa or not pb:
            continue
        best = min(
            ((x, y) for x in pa for y in pb),
            key=lambda xy: math.hypot(xy[0]["c"][0] - xy[1]["c"][0], xy[0]["c"][1] - xy[1]["c"][1]),
        )
        x, y = best
        d = math.hypot(x["c"][0] - y["c"][0], x["c"][1] - y["c"][1])
        mid = ((x["c"][0] + y["c"][0]) / 2, (x["c"][1] + y["c"][1]) / 2 - 6)
        bridges.append(
            {
                "c": mid,
                "handle": f"{a}+{b}",
                "pair": [a, b],
                "rx": max(14.0, min(34.0, d * 0.30)),
                "ry": max(10.0, min(22.0, d * 0.30 * 0.62)),
                "n": 99,
                "reach": d > 210,
            }
        )

    def pt(p):
        return [p[0], p[1]]

    return {
        "elements": elements,
        "crosses": [list(c) for c in crosses],
        "primaries": {h: [pt(p) for p in pts] for h, pts in primaries.items()},
        "wood": [
            {"pts": [pt(p) for p in w[0]], "wRoot": w[1], "wTip": w[2], "gen": w[3], "handle": w[4]["handle"]}
            for w in gd.WOOD
        ],
        "twigs": [[pt(a), pt(b)] for a, b in gd.TWIGS],
        "anchors": {h: [pt(p) for p in v] for h, v in gd.ANCHORS.items()},
        "pads": {
            h: [{"c": pt(p["c"]), "rx": p["rx"], "ry": p["ry"], "n": p["n"]} for p in v]
            for h, v in pads_by.items()
        },
        "bridges": [
            {"c": pt(b["c"]), "handle": b["handle"], "rx": b["rx"], "ry": b["ry"], "reach": b["reach"]}
            for b in bridges
        ],
    }


def rng_self_check() -> dict:
    out: dict[str, list] = {}
    r = seed_rng("grammar5", "B1-T2")
    out["random5"] = [r.random() for _ in range(5)]
    r = seed_rng("grammar5", "B1-T2")
    out["uniform3"] = [r.uniform(-1.3, 1.3) for _ in range(3)]
    r = seed_rng("grammar5", "B1-T2")
    out["choice6"] = [r.choice((1, -1)) for _ in range(6)]
    r = seed_rng("grammar5", "B1-T2")
    out["gauss4"] = [r.gauss(0.0, 1.0) for _ in range(4)]
    r = seed_rng("grammar5", "B1-T2")
    out["randint4"] = [r.randint(35, 105) for _ in range(4)]
    r = seed_rng("grammar5", "B1-T2")
    out["mixed"] = [
        r.uniform(0.85, 1.12),
        r.choice((1, -1)),
        r.gauss(0.0, 10.0),
        r.randint(95, 175),
        r.random(),
    ]
    return out


def main() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entities = {e["id"]: e for e in doc["entities"]}
    edges = doc.get("edges", [])
    trees = {}
    for pid in ("B1", "B2"):
        elements, crosses = deal(entities[pid], edges)
        trees[pid] = grow_tree(elements, crosses)
    dump = {
        "source": "growth_demo3.py (canonical) via growthHarness.py",
        "fixture": "maeve-palace-study/fixture.json sha256 6a85e7f82657bda28d7dd785b138d8cad5ea78422cd3e33772f10bf7d2753949",
        "rngCheck": rng_self_check(),
        "trunkPath": [[p[0], p[1]] for p in gd.TRUNK_PATH],
        "trees": trees,
    }
    out = HERE / "__fixtures__" / "growth-fixture.json"
    out.write_text(json.dumps(dump), encoding="utf-8")
    for pid, t in trees.items():
        print(
            pid,
            "elements", len(t["elements"]),
            "wood", len(t["wood"]),
            "twigs", len(t["twigs"]),
            "pads", {h: len(v) for h, v in t["pads"].items()},
            "bridges", len(t["bridges"]),
        )
    print("wrote", out)


if __name__ == "__main__":
    main()
