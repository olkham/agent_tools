#!/usr/bin/env python3
"""Stripboard (Veroboard) layout checker, renderer and build-guide generator.

Copper strips run along rows. Input coordinates are zero-based [column,row] seen from the
component side. Drawings and guides use Veroboard names: rows A, B, ... (AA after Z) and
columns from 1, so [0,0] is A1. Standard library only; PyMuPDF (fitz) adds PNG output.
"""
import argparse
import html
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PITCH, MARGIN, TOP = 32, 48, 100          # SVG px per hole, left margin, top of row A
FOOTPRINTS = ("axial", "radial", "header", "dip", "module", "tactile")
CUT_STYLES = ("hole", "between", "prefer-hole")
POLAR_TYPES = {"diode", "led", "zener", "schottky"}           # pins A/K
LOW_TYPES = {"resistor", "diode", "zener", "schottky", "wire"}
SOCKET_TYPES = {"header", "connector", "socket", "ic"}
ROTATE = {0: lambda u, v: (u, v), 90: lambda u, v: (-v, u),     # clockwise on the component-side view
          180: lambda u, v: (-u, -v), 270: lambda u, v: (v, -u)}
PALETTE = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf", "#8c564b", "#e377c2"]
BOARD, COPPER, COPPER_UNUSED, CUT_RED = "#e0c38f", "#c27c3a", "#d8c3a2", "#d62222"


# ----------------------------------------------------------------------------- notation
def row_name(y):
    """0 -> A, 25 -> Z, 26 -> AA, 27 -> AB ..."""
    s, n = "", y + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def hole_name(p):
    return f"{row_name(p[1])}{p[0] + 1}"


def between_name(p):
    return f"{hole_name(p)}|{hole_name((p[0] + 1, p[1]))}"


# ----------------------------------------------------------------------------- input helpers
def need(obj, key, ctx):
    if not isinstance(obj, dict):
        raise ValueError(f"{ctx}: expected an object, got {obj!r}")
    if key not in obj:
        raise ValueError(f'{ctx}: missing "{key}"')
    return obj[key]


def as_int(v, ctx, lo=None, hi=None):
    if type(v) is not int or (lo is not None and v < lo) or (hi is not None and v > hi):
        rng = f" in {lo}..{hi}" if hi is not None else (f" >= {lo}" if lo is not None else "")
        raise ValueError(f"{ctx}: expected an integer{rng}, got {v!r}")
    return v


def as_num(v, ctx):
    if type(v) not in (int, float) or v < 0:
        raise ValueError(f"{ctx}: expected a number >= 0, got {v!r}")
    return float(v)


def net_name(v, ctx):
    """None, missing or "NC" mean not connected."""
    if v is None or v == "NC":
        return None
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f'{ctx}: net names must be nonempty strings (or null / "NC")')
    return v


def make_point(w, h):
    def point(p, ctx):
        if not isinstance(p, (list, tuple)) or len(p) != 2 or any(type(v) is not int for v in p):
            raise ValueError(f"{ctx}: invalid coordinate {p!r} (expected [column,row] integers)")
        if not (0 <= p[0] < w and 0 <= p[1] < h):
            raise ValueError(f"{ctx}: hole {list(p)} is outside the {w}x{h} board")
        return (p[0], p[1])
    return point


def dedupe(names, ref):
    """Repeated names get #2, #3 ... in order: GND, GND#2."""
    seen, out = defaultdict(int), []
    for n in names:
        seen[n] += 1
        out.append(n if seen[n] == 1 else f"{n}#{seen[n]}")
    if len(set(out)) != len(out):
        raise ValueError(f"{ref}: pin names clash after numbering duplicates: {out}")
    return out


# ----------------------------------------------------------------------------- footprints
def expand_footprint(c, ref, t):
    """Pins, bridges, body shape and pin labels in the footprint's own frame (rotation 0:
    pins advance along +u = +column). Second pin rows sit at negative v."""
    fp, pins, bridges, labels = c["footprint"], [], [], []

    def add(key, number, u, v, aliases=()):
        pins.append({"key": str(key), "number": str(number), "uv": (u, v), "aliases": list(aliases)})

    def pin_names(n):
        names = c.get("pin_names")
        if names is None:
            return [str(i + 1) for i in range(n)], False
        if not isinstance(names, list) or len(names) != n or not all(isinstance(s, str) and s for s in names):
            raise ValueError(f"{ref}: pin_names must list {n} nonempty strings")
        return dedupe(names, ref), True

    if fp == "axial":
        span = as_int(c.get("span", 4), f"{ref}.span", 1, 100)
        diode = t in POLAR_TYPES
        if diode:
            add("A", 2, 0, 0)
            add("K", 1, span, 0)
        else:
            add("1", 1, 0, 0)
            add("2", 2, span, 0)
        length = max(0.4, min(span - 0.9, 1.6 if diode else 2.6))
        shape = {"kind": "axial", "a": (0, 0), "b": (span, 0), "len": length, "diode": diode, "band": diode}
    elif fp == "radial":
        pitch = as_int(c.get("pitch", 1), f"{ref}.pitch", 1, 20)
        dia = as_num(c.get("diameter", 2), f"{ref}.diameter")
        polar = t in POLAR_TYPES
        add("A" if polar else "1", 2 if polar else 1, 0, 0)
        add("K" if polar else "2", 1 if polar else 2, pitch, 0)
        shape = {"kind": "radial", "c": (pitch / 2, 0), "r": dia / 2, "flat": (1, 0) if polar else None}
    elif fp == "header":
        n = as_int(c.get("pins"), f"{ref}.pins (pin count for a header)", 1, 100)
        keys, named = pin_names(n)
        for i, k in enumerate(keys):
            add(k, i + 1, i, 0)
            if named:
                labels.append((k, (i, 0), (0, -1), "#222"))
        shape = {"kind": "rect", "style": "female" if c.get("female") else "header",
                 "box": (-0.5, -0.48, n - 0.5, 0.48)}
    elif fp == "dip":
        n = as_int(c.get("pins"), f"{ref}.pins (pin count for a DIP)", 4, 64)
        if n % 2:
            raise ValueError(f"{ref}: a DIP needs an even pin count, got {n}")
        rs = as_int(c.get("row_spacing", 3), f"{ref}.row_spacing", 2, 20)
        keys, _ = pin_names(n)
        n2 = n // 2
        for k in range(n2):
            add(keys[k], k + 1, k, 0)
            labels.append((str(k + 1), (k, 0), (0, -1), "#fff"))
        for j in range(n2):
            add(keys[n2 + j], n2 + j + 1, n2 - 1 - j, -rs)
            labels.append((str(n2 + j + 1), (n2 - 1 - j, -rs), (0, 1), "#fff"))
        shape = {"kind": "rect", "style": "dip", "box": (-0.5, -rs + 0.3, n2 - 0.5, -0.3), "notch": (-0.5, -rs / 2)}
    elif fp == "module":
        rs = as_int(need(c, "row_spacing", ref), f"{ref}.row_spacing", 1, 40)
        left, right = c.get("left", []), c.get("right", [])
        for side, lst in (("left", left), ("right", right)):
            if not isinstance(lst, list) or not all(s is None or (isinstance(s, str) and s) for s in lst):
                raise ValueError(f"{ref}.{side}: expected a list of pin names (null = no pin there)")
        numbering = c.get("numbering", "sequential")
        if numbering not in ("sequential", "ccw", "odd_even"):
            raise ValueError(f"{ref}.numbering: use sequential, ccw or odd_even")
        nl, nr = len(left), len(right)
        placed = [(s, "L", i) for i, s in enumerate(left) if s] + [(s, "R", i) for i, s in enumerate(right) if s]
        if not placed:
            raise ValueError(f"{ref}: a module needs pin names in left and/or right")
        keys = dedupe([s for s, _, _ in placed], ref)
        for key, (_, side, i) in zip(keys, placed):
            if side == "L":
                number = {"sequential": i + 1, "ccw": i + 1, "odd_even": 2 * i + 1}[numbering]
                add(key, number, i, 0, [f"L{i + 1}"])
                labels.append((key, (i, 0), (0, -1), "#fff"))
            else:
                number = {"sequential": nl + i + 1, "ccw": nl + nr - i, "odd_even": 2 * i + 2}[numbering]
                add(key, number, i, -rs, [f"R{i + 1}"])
                labels.append((key, (i, -rs), (0, 1), "#fff"))
        body = c.get("body", {}) or {}
        if not isinstance(body, dict):
            raise ValueError(f"{ref}.body: expected an object")
        ext = {k: as_num(body.get(k, 0), f"{ref}.body.{k}")
               for k in ("extend_start", "extend_end", "extend_left", "extend_right")}
        n = max(nl, nr)
        shape = {"kind": "rect", "style": "module",
                 "box": (-0.5 - ext["extend_start"], -rs - 0.5 - ext["extend_right"],
                         n - 0.5 + ext["extend_end"], 0.5 + ext["extend_left"])}
    elif fp == "tactile":
        # 6x6 mm switch: real pitch 6.5 x 4.5 mm, approximated as 3 holes across x 2 holes along.
        add("1", 1, 0, 0)
        add("2", 2, 0, 3)
        add("3", 3, 2, 0)
        add("4", 4, 2, 3)
        bridges = [["1", "2"], ["3", "4"]]
        shape = {"kind": "rect", "style": "tactile", "box": (1 - 1.18, 1.5 - 1.18, 1 + 1.18, 1.5 + 1.18), "c": (1, 1.5)}
    else:
        raise ValueError(f"{ref}: unknown footprint {fp!r}; use one of {', '.join(FOOTPRINTS)}")
    return {"pins": pins, "bridges": bridges, "shape": shape, "labels": labels}


def transform_shape(s, place, turn):
    s = dict(s)
    for k in ("a", "b", "c", "notch"):
        if s.get(k) is not None:
            s[k] = place(*s[k])
    if s.get("flat"):
        s["flat"] = turn(*s["flat"])
    if "box" in s:
        (x0, y0), (x1, y1) = place(*s["box"][:2]), place(*s["box"][2:])
        s["box"] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return s


def explicit_shape(t, pins):
    by_key = {p["key"]: p for p in pins}
    if len(pins) == 2 and (t == "resistor" or t in POLAR_TYPES):
        a, b = pins[0]["at"], pins[1]["at"]
        has_ak = "A" in by_key and "K" in by_key
        if has_ak:
            a, b = by_key["A"]["at"], by_key["K"]["at"]
        if t == "led":
            d = math.dist(a, b)
            return {"kind": "radial", "c": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "r": 1.0,
                    "flat": ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if has_ak else None}
        diode = t in POLAR_TYPES
        length = max(0.4, min(math.dist(a, b) - 0.9, 1.6 if diode else 2.6))
        return {"kind": "axial", "a": a, "b": b, "len": length, "diode": diode, "band": diode and has_ak}
    xs, ys = [p["at"][0] for p in pins], [p["at"][1] for p in pins]
    return {"kind": "rect", "style": "generic", "box": (min(xs) - 0.4, min(ys) - 0.4, max(xs) + 0.4, max(ys) + 0.4)}


def find_pin(comp, name):
    name = str(name)
    for attr in ("key", "number"):
        for p in comp["pins"]:
            if p[attr] == name:
                return p
    for p in comp["pins"]:
        if name in p["aliases"]:
            return p
    raise ValueError(f"{comp['ref']}: no pin {name!r}; pins are {', '.join(p['key'] for p in comp['pins'])}")


def parse_component(c, point):
    ref = need(c, "ref", "component")
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"Invalid component reference: {ref!r}")
    typ = c.get("type") or ""
    if not isinstance(typ, str):
        raise ValueError(f"{ref}.type: expected a string")
    t, fp = typ.lower(), c.get("footprint")
    comp = {"ref": ref, "type": typ, "footprint": fp, "rotation": 0, "color": c.get("color"),
            **{k: str(c.get(k) or "") for k in ("value", "description", "part", "label")}}

    def new_pin(key, number, at, net, aliases=()):
        return {"ref": ref, "key": str(key), "number": str(number), "at": at, "net": net,
                "aliases": list(aliases), "label": f"{ref}.{key}", "inherited": False}

    if fp is None:
        spec_pins = need(c, "pins", ref)
        if not isinstance(spec_pins, dict) or not spec_pins:
            raise ValueError(f"{ref}: pins must be a nonempty object (or give a footprint)")
        comp["pins"] = [new_pin(k, s.get("number", k) if isinstance(s, dict) else k,
                                point(need(s, "at", f"{ref}.{k}"), f"{ref}.{k}"),
                                net_name(s.get("net"), f"{ref}.{k}")) for k, s in spec_pins.items()]
        comp["shape"] = explicit_shape(t, comp["pins"])
        comp["labels"] = [] if comp["shape"]["kind"] != "rect" else \
            [(p["key"], p["at"], None, "#222") for p in comp["pins"]]
        builtin_bridges = []
    else:
        if fp not in FOOTPRINTS:
            raise ValueError(f"{ref}: unknown footprint {fp!r}; use one of {', '.join(FOOTPRINTS)}")
        at = point(need(c, "at", ref), f"{ref}.at")
        rot = c.get("rotation", 0)
        if type(rot) is not int or rot not in ROTATE:
            raise ValueError(f"{ref}.rotation: must be 0, 90, 180 or 270, got {rot!r}")
        comp["rotation"] = rot
        local = expand_footprint(c, ref, t)
        turn = ROTATE[rot]

        def place(u, v):
            du, dv = turn(u, v)
            return (at[0] + du, at[1] + dv)
        comp["pins"] = [new_pin(lp["key"], lp["number"], point(list(place(*lp["uv"])), f"{ref}.{lp['key']} (footprint)"),
                                None, lp["aliases"]) for lp in local["pins"]]
        comp["shape"] = transform_shape(local["shape"], place, turn)
        comp["labels"] = [(text, place(*uv), turn(*d), col) for text, uv, d, col in local["labels"]]
        builtin_bridges = local["bridges"]
    numbers = [p["number"] for p in comp["pins"]]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"{ref}: duplicate pin numbers {numbers}")

    nets = c.get("nets", {}) or {}
    if not isinstance(nets, dict):
        raise ValueError(f"{ref}.nets: expected an object {{pin: net}}")
    assigned = {}
    for k, v in nets.items():
        p = find_pin(comp, k)
        if p["key"] in assigned:
            raise ValueError(f"{ref}.nets: pin {p['key']} is given twice ({assigned[p['key']]!r} and {k!r})")
        assigned[p["key"]] = k
        p["net"] = net_name(v, f"{ref}.nets[{k!r}]")

    groups = [list(g) for g in builtin_bridges]
    user = c.get("bridges", []) or []
    if not isinstance(user, list):
        raise ValueError(f"{ref}.bridges: expected a list of pin lists")
    for g in user:
        if not isinstance(g, list) or len(g) < 2:
            raise ValueError(f"{ref}.bridges: each group needs at least two pins, got {g!r}")
        groups.append([find_pin(comp, k)["key"] for k in g])
    comp["bridges"] = [[find_pin(comp, k) for k in g] for g in groups]
    # schematic pin -> layout pins; the tactile default follows KiCad's 2-pin SW_Push symbol
    npins = c.get("netlist_pins", {"1": ["1", "2"], "2": ["3", "4"]} if fp == "tactile" else {})
    if not isinstance(npins, dict):
        raise ValueError(f"{ref}.netlist_pins: expected an object {{schematic_pin: [layout pins]}}")
    comp["netlist_pins"] = {str(k): [find_pin(comp, x) for x in (v if isinstance(v, list) else [v])] for k, v in npins.items()}
    for g in comp["bridges"]:                      # an unnamed pin takes its bridge group's net
        named = {p["net"] for p in g if p["net"]}
        if len(named) == 1:
            for p in g:
                if not p["net"]:
                    p["net"], p["inherited"] = next(iter(named)), True
    for p in comp["pins"]:                          # private net for NC pins (shared within a bridge group)
        p["nc_key"] = None if p["net"] else f"NC:{p['label']}"
    for g in comp["bridges"]:
        ncs = [p for p in g if not p["net"]]
        for p in ncs:
            p["nc_key"] = ncs[0]["nc_key"]
    comp["bbox"] = body_bbox(comp["shape"])
    return comp


def body_bbox(s):
    if s["kind"] == "axial":
        (ax, ay), (bx, by) = s["a"], s["b"]
        d = math.dist(s["a"], s["b"])
        ux, uy = (bx - ax) / d, (by - ay) / d
        mx, my, hl, hw = (ax + bx) / 2, (ay + by) / 2, s["len"] / 2, 0.4
        pts = [(mx + ux * su * hl - uy * sv * hw, my + uy * su * hl + ux * sv * hw) for su in (-1, 1) for sv in (-1, 1)]
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    if s["kind"] == "radial":
        (cx, cy), r = s["c"], s["r"] * 0.95
        return (cx - r, cy - r, cx + r, cy + r)
    return s["box"]


# ----------------------------------------------------------------------------- cuts and strips
def parse_cuts(raw, point, w, occupied):
    hole_cuts, between, order = set(), set(), []
    if not isinstance(raw, list):
        raise ValueError("cuts: expected a list")
    for i, cdef in enumerate(raw, 1):
        ctx = f"cut {i}"
        if isinstance(cdef, dict):
            if set(cdef) != {"between"}:
                raise ValueError(f'{ctx}: expected [x,y] or {{"between":[x,y]}}, got {cdef!r}')
            p = point(cdef["between"], ctx)
            if p[0] >= w - 1:
                raise ValueError(f"{ctx}: a between-cut at {list(p)} needs a column to its right")
            if p in between:
                raise ValueError(f"Duplicate track cut: between {between_name(p)}")
            between.add(p)
            order.append({"kind": "between", "at": p, "auto": False})
        else:
            p = point(cdef, ctx)
            if p in hole_cuts:
                raise ValueError(f"Duplicate track cut: {hole_name(p)}")
            if p in occupied:
                raise ValueError(f"Track cut on an occupied hole {hole_name(p)} {list(p)}: {occupied[p]}")
            hole_cuts.add(p)
            order.append({"kind": "hole", "at": p, "auto": False})
    return hole_cuts, between, order


def strip_segments(w, h, hole_cuts, between):
    """Copper segments as (row, first column, last column) plus a hole -> segment index map."""
    segs, seg_of = [], {}
    for y in range(h):
        start = None
        for x in range(w):
            if (x, y) in hole_cuts:
                if start is not None:
                    segs.append((y, start, x - 1))
                    start = None
                continue
            if start is None:
                start = x
            seg_of[(x, y)] = len(segs)
            if (x, y) in between or x == w - 1:
                segs.append((y, start, x))
                start = None
    return segs, seg_of


def separated(y, a, b, hole_cuts, between):
    return any((x, y) in hole_cuts for x in range(a + 1, b)) or any((x, y) in between for x in range(a, b))


def infer_link_nets(links, pins, seg_of):
    """A link without "net" takes the net of an end whose strip segment (before auto-cuts) holds
    pins (or already-known links) of exactly one net."""
    while True:
        holders = defaultdict(set)
        for p in pins:
            if p["net"]:
                holders[seg_of[p["at"]]].add(p["net"])
        for l in links:
            if l["net"]:
                holders[seg_of[l["a"]]].add(l["net"])
                holders[seg_of[l["b"]]].add(l["net"])
        changed = False
        for l in links:
            if l["net"]:
                continue
            na, nb = holders[seg_of[l["a"]]], holders[seg_of[l["b"]]]
            cands = [n for n in (na, nb) if len(n) == 1]
            if len(cands) == 2 and cands[0] != cands[1]:
                continue                                  # joins two different nets: leave it to the short check
            if cands:
                l["net"], l["net_source"] = next(iter(cands[0])), "inferred"
                changed = True
        if not changed:
            return


def auto_cut(pins, links, occupied, hole_cuts, between, order, style):
    anchors = defaultdict(list)
    for p in pins:
        anchors[p["at"][1]].append((p["at"][0], p["net"] or p["nc_key"], p["label"]))
    for l in links:
        for end in (l["a"], l["b"]):
            anchors[end[1]].append((end[0], l["net"], f"{l['label']} end {hole_name(end)}"))
    for y in sorted(anchors):
        row = sorted(anchors[y], key=lambda a: a[0])
        for (a, ka, la), (b, kb, lb) in zip(row, row[1:]):
            if (ka == kb and ka is not None) or separated(y, a, b, hole_cuts, between):
                continue
            if ka is None or kb is None:
                which = la if ka is None else lb
                raise ValueError(f'--auto-cuts: cannot tell which net {which} carries (it shares strip {row_name(y)} '
                                 f'with {lb if ka is None else la}); add "net" to that link')
            free = [x for x in range(a + 1, b) if (x, y) not in occupied]
            if style != "between" and free:
                p = (free[len(free) // 2], y)
                hole_cuts.add(p)
                order.append({"kind": "hole", "at": p, "auto": True})
            elif style == "hole":
                raise ValueError(f"--auto-cuts: no free hole to cut between {la} ({hole_name((a, y))}) and "
                                 f"{lb} ({hole_name((b, y))}); use --cut-style prefer-hole or between, or move a part")
            else:
                p = (a + (b - a - 1) // 2, y)
                between.add(p)
                order.append({"kind": "between", "at": p, "auto": True})


# ----------------------------------------------------------------------------- netlist
def parse_kicad_netlist(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"netlist: not valid XML ({e})") from None
    refs = {c.get("ref") for c in root.iter("comp") if c.get("ref")}
    nets = {}
    for net in root.iter("net"):
        name = net.get("name") or f"net code {net.get('code')}"
        if name in nets:
            name = f"{name} (code {net.get('code')})"
        nets[name] = [(n.get("ref"), n.get("pin") or "", n.get("pinfunction") or "") for n in net.iter("node")]
        refs.update(r for r, _, _ in nets[name] if r)
    if not nets:
        raise ValueError("netlist: no <net> elements (expected `kicad-cli sch export netlist --format kicadxml`)")
    return refs, nets


def match_pins(comp, pin, func):
    if pin in comp["netlist_pins"]:
        return comp["netlist_pins"][pin]
    for test in (lambda p: p["number"] == pin, lambda p: p["key"] == pin,
                 lambda p: bool(func) and (p["key"] == func or p["key"].split("#")[0] == func)):
        hits = [p for p in comp["pins"] if test(p)]
        if hits:
            return hits
    return []


def check_netlist(text, ignore, comps, find):
    refs, nets = parse_kicad_netlist(text)
    ignore, by_ref, out = set(ignore), {c["ref"]: c for c in comps}, []
    for ref in sorted(refs - set(by_ref) - ignore):
        out.append({"kind": "ref_missing_in_layout", "ref": ref,
                    "message": f"{ref} is in the schematic but not on the board (use --netlist-ignore {ref} if it is off-board)"})
    for ref in sorted(set(by_ref) - refs - ignore):
        out.append({"kind": "ref_missing_in_schematic", "ref": ref, "message": f"{ref} is on the board but not in the schematic"})
    matched, net_clusters = set(), {}
    for name, nodes in nets.items():
        clusters = defaultdict(list)
        for ref, pin, func in nodes:
            if ref in ignore or ref not in by_ref:
                continue
            hits = match_pins(by_ref[ref], pin, func)
            if not hits:
                out.append({"kind": "pin_missing_in_layout", "ref": ref, "pin": pin, "net": name,
                            "message": f"{ref} pin {pin}{f' ({func})' if func else ''} of net {name} is not on the board part"})
            for p in hits:
                matched.add(p["label"])
                clusters[find(p["at"])].append(f"{p['label']} {hole_name(p['at'])}")
        net_clusters[name] = clusters
        if len(clusters) > 1:
            groups = sorted(sorted(g) for g in clusters.values())
            out.append({"kind": "split", "net": name, "groups": groups,
                        "message": f"schematic net {name} is split on the board: " + " | ".join(", ".join(g) for g in groups)})
    root_nets = defaultdict(set)
    for name, clusters in net_clusters.items():
        for root in clusters:
            root_nets[root].add(name)
    for root, names in root_nets.items():
        if len(names) > 1:
            pins = sorted({p for n in names for p in net_clusters[n][root]})
            out.append({"kind": "merged", "nets": sorted(names), "pins": pins,
                        "message": f"schematic nets {', '.join(sorted(names))} are connected on the board ({', '.join(pins)})"})
    for c in comps:
        if c["ref"] in refs and c["ref"] not in ignore:
            for p in c["pins"]:
                if p["net"] and p["label"] not in matched:
                    out.append({"kind": "pin_missing_in_schematic", "ref": c["ref"], "pin": p["key"],
                                "message": f"{p['label']} (net {p['net']}) is not in any schematic net"})
    return out


# ----------------------------------------------------------------------------- physical checks
def physical_warnings(w, h, comps, links, occupied, hole_cuts, between):
    out = []

    def warn(kind, msg):
        out.append({"kind": kind, "message": msg})
    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["bbox"], b["bbox"]
            if min(ax1, bx1) - max(ax0, bx0) > 0.05 and min(ay1, by1) - max(ay0, by0) > 0.05:
                warn("overlap", f"bodies of {a['ref']} and {b['ref']} overlap")
    for c in comps:
        x0, y0, x1, y1 = c["bbox"]
        for p, who in occupied.items():
            if not who.startswith(c["ref"] + ".") and x0 + 0.1 < p[0] < x1 - 0.1 and y0 + 0.1 < p[1] < y1 - 0.1:
                warn("covered_hole", f"body of {c['ref']} covers {hole_name(p)}, used by {who}")
        if x0 < -0.5 or y0 < -0.5 or x1 > w - 0.5 or y1 > h - 0.5:
            warn("off_board", f"body of {c['ref']} extends past the board edge")
    for l in links:
        (ax, ay), (bx, by) = l["a"], l["b"]
        if not l["insulated"]:
            for p, who in occupied.items():
                if p in (l["a"], l["b"]):
                    continue
                t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
                if math.dist(p, (ax + t * (bx - ax), ay + t * (by - ay))) < 0.35:
                    warn("bare_link", f"bare {l['label']} passes over {hole_name(p)} ({who}); insulate it or reroute")
        for x, y in (l["a"], l["b"]):
            if {(x - 1, y), (x + 1, y)} & hole_cuts or {(x - 1, y), (x, y)} & between:
                warn("link_by_cut", f"{l['label']} end {hole_name((x, y))} is next to a track cut; check the solder joint does not bridge it")
    return out


# ----------------------------------------------------------------------------- build (validate + analyse)
def build(data, *, auto_cuts=False, cut_style="prefer-hole", netlist=None, netlist_ignore=()):
    if cut_style not in CUT_STYLES:
        raise ValueError(f"cut_style must be one of {', '.join(CUT_STYLES)}")
    board = need(data, "board", "input")
    w = as_int(need(board, "columns", "board"), "board.columns", 2, 200)
    h = as_int(need(board, "rows", "board"), "board.rows", 1, 200)
    name = board.get("name") or ""
    point = make_point(w, h)
    comps, occupied = [], {}
    for c in data.get("components", []):
        comp = parse_component(c, point)
        if any(comp["ref"] == o["ref"] for o in comps):
            raise ValueError(f"Duplicated component reference: {comp['ref']!r}")
        for p in comp["pins"]:
            if p["at"] in occupied:
                raise ValueError(f"One lead per hole: {hole_name(p['at'])} {list(p['at'])} holds {occupied[p['at']]} and {p['label']}")
            occupied[p["at"]] = p["label"]
        comps.append(comp)
    pins = [p for c in comps for p in c["pins"]]
    links = []
    for i, l in enumerate(data.get("links", []), 1):
        ctx = f"link {i}"
        a, b = point(need(l, "from", ctx), ctx), point(need(l, "to", ctx), ctx)
        if a == b:
            raise ValueError(f"{ctx}: both ends in hole {hole_name(a)}")
        for p in (a, b):
            if p in occupied:
                raise ValueError(f"One lead per hole: {ctx} end {hole_name(p)} {list(p)} is already used by {occupied[p]}")
            occupied[p] = ctx
        net = net_name(l.get("net"), ctx)
        insulated = l.get("insulated", True)
        if type(insulated) is not bool:
            raise ValueError(f"{ctx}.insulated: expected true or false")
        color = l.get("color")
        if color is not None and not isinstance(color, str):
            raise ValueError(f"{ctx}.color: expected a string")
        links.append({"label": ctx, "a": a, "b": b, "net": net, "net_source": "given" if net else None,
                      "insulated": insulated, "color": color})
    hole_cuts, between, cut_order = parse_cuts(data.get("cuts", []), point, w, occupied)

    _, seg_of = strip_segments(w, h, hole_cuts, between)
    infer_link_nets(links, pins, seg_of)
    if auto_cuts:
        auto_cut(pins, links, occupied, hole_cuts, between, cut_order, cut_style)

    parent = {}

    def find(p):
        parent.setdefault(p, p)
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def union(a, b):
        parent[find(a)] = find(b)
    for y in range(h):
        for x in range(w):
            if (x, y) not in hole_cuts:
                find((x, y))
                if x + 1 < w and (x, y) not in between and (x + 1, y) not in hole_cuts:
                    union((x, y), (x + 1, y))
    for l in links:
        union(l["a"], l["b"])
    bridges = []
    for c in comps:
        for g in c["bridges"]:
            for p in g[1:]:
                union(g[0]["at"], p["at"])
            bridges.append({"ref": c["ref"], "pins": [p["key"] for p in g], "holes": [hole_name(p["at"]) for p in g],
                            "note": f"{c['ref']} pins {'+'.join(p['key'] for p in g)} are connected inside the part"})

    cl_nets, cl_pins, cl_links = defaultdict(set), defaultdict(list), defaultdict(list)
    for p in pins:
        cl_pins[find(p["at"])].append(p)
        if p["net"]:
            cl_nets[find(p["at"])].add(p["net"])
    for l in links:
        cl_links[find(l["a"])].append(l)
        if l["net"]:
            cl_nets[find(l["a"])].add(l["net"])

    def cl_label(root):
        if cl_nets[root]:
            return "/".join(sorted(cl_nets[root]))
        if cl_pins[root]:
            return "NC"
        return "(no net)" if cl_links[root] else ""

    net_pins = defaultdict(list)
    for p in pins:
        if p["net"]:
            net_pins[p["net"]].append(p)
    shorts = sorted(sorted(s) for s in cl_nets.values() if len(s) > 1)
    disconnected = {n: k for n, ps in sorted(net_pins.items()) if (k := len({find(p["at"]) for p in ps})) > 1}
    nc_conflicts = []
    for p in pins:
        if p["net"]:
            continue
        r = find(p["at"])
        others = {f"{q['label']} (NC)" for q in cl_pins[r] if not q["net"] and q["nc_key"] != p["nc_key"]}
        connected = sorted(cl_nets[r] | others)
        if connected:
            nc_conflicts.append({"pin": p["label"], "at": list(p["at"]), "hole": hole_name(p["at"]), "connected_to": connected})
    mismatches = check_netlist(netlist, netlist_ignore, comps, find) if netlist is not None else []
    warnings = physical_warnings(w, h, comps, links, occupied, hole_cuts, between)

    segs, _ = strip_segments(w, h, hole_cuts, between)
    segments = []
    for y, x0, x1 in segs:
        r = find((x0, y))
        segments.append({"row": row_name(y), "y": y, "from": x0, "to": x1,
                         "holes": f"{hole_name((x0, y))}-{hole_name((x1, y))}", "net": cl_label(r) or None,
                         "used": bool(cl_pins[r] or cl_links[r])})

    def side_label(p):
        return cl_label(find(p)) or "unused" if 0 <= p[0] < w and p not in hole_cuts else None
    cut_list = []
    for cut in sorted(cut_order, key=lambda c: (c["at"][1], c["at"][0], c["kind"])):
        (x, y), hole = cut["at"], cut["kind"] == "hole"
        left, right = ((x - 1, y), (x + 1, y)) if hole else ((x, y), (x + 1, y))
        cut_list.append({"kind": cut["kind"], "at": list(cut["at"]), "name": hole_name(cut["at"]) if hole else between_name(cut["at"]),
                         "auto": cut["auto"], "separates": [side_label(left), side_label(right)]})

    # continuity checks for the guide: what should and must not beep
    no_beep, seen = [], set()

    def add_no_beep(pa, pb, why):
        ra, rb = find(pa), find(pb)
        la, lb = cl_label(ra), cl_label(rb)
        if ra == rb or not la or not lb or (la == lb and la != "NC") or (why.startswith("adjacent") and (ra, rb) in seen):
            return
        seen.add((ra, rb))
        no_beep.append({"a": hole_name(pa), "b": hole_name(pb), "nets": [la, lb], "why": why})
    for cut in cut_list:
        (x, y) = cut["at"]
        pa, pb = ((x - 1, y), (x + 1, y)) if cut["kind"] == "hole" else ((x, y), (x + 1, y))
        if pa[0] >= 0 and pb[0] < w and pa not in hole_cuts and pb not in hole_cuts:
            add_no_beep(pa, pb, f"across cut {cut['name']}")
    by_row = defaultdict(list)
    for s in segs:
        by_row[s[0]].append(s)
    for y in range(h - 1):
        for _, a0, a1 in by_row[y]:
            for _, b0, b1 in by_row[y + 1]:
                lo, hi = max(a0, b0), min(a1, b1)
                if lo <= hi:
                    xs = [x for x in range(lo, hi + 1) if (x, y) in occupied or (x, y + 1) in occupied] or [lo]
                    add_no_beep((xs[0], y), (xs[0], y + 1), "adjacent strips")
    beep = {n: [f"{p['label']} {hole_name(p['at'])}" for p in ps] for n, ps in sorted(net_pins.items()) if len(ps) > 1}

    def pin_info(p):
        return {"at": list(p["at"]), "hole": hole_name(p["at"]), "net": p["net"], "number": p["number"],
                **({"net_inherited_from_bridge": True} if p["inherited"] else {})}
    report = {
        "valid": not (shorts or disconnected or nc_conflicts or mismatches),
        "board": {"name": name, "columns": w, "rows": h, "row_labels": f"A-{row_name(h - 1)}", "column_labels": f"1-{w}"},
        "shorts": shorts, "disconnected": disconnected, "nc_conflicts": nc_conflicts,
        "netlist_checked": netlist is not None, "netlist_mismatches": mismatches,
        "warnings": warnings,
        "cuts": [list(c["at"]) if c["kind"] == "hole" else {"between": list(c["at"])} for c in cut_list],
        "cut_list": cut_list,
        "links": len(links),
        "link_list": [{"from": list(l["a"]), "to": list(l["b"]), "from_hole": hole_name(l["a"]), "to_hole": hole_name(l["b"]),
                       "net": l["net"], "net_source": l["net_source"], "insulated": l["insulated"], "color": l["color"]}
                      for l in links],
        "terminals": sum(map(len, net_pins.values())),
        "pins": {p["label"]: pin_info(p) for p in pins},
        "nets": {n: [hole_name(p["at"]) for p in ps] for n, ps in sorted(net_pins.items())},
        "bridges": bridges,
        "segments": segments,
        "continuity_checks": {"beep": beep, "no_beep": no_beep},
    }
    return {"w": w, "h": h, "name": name, "comps": comps, "links": links, "hole_cuts": hole_cuts, "between": between,
            "occupied": occupied, "segments": segments, "report": report}


# ----------------------------------------------------------------------------- SVG rendering
def fmt(v):
    v = round(v, 1)
    return str(int(v)) if v == int(v) else str(v)


def esc(s):
    return html.escape(str(s), quote=True)


def text(x, y, s, size=10, fill="#222", anchor="middle", weight="normal", halo=None, rot=0, cls=""):
    tr = f' transform="rotate({rot} {fmt(x)} {fmt(y)})"' if rot else ""
    c = f' class="{cls}"' if cls else ""
    base = (f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}"{tr}{c}'
            ' fill="{0}"{1}>' + esc(s) + "</text>")
    under = base.format(halo, f' stroke="{halo}" stroke-width="3" stroke-linejoin="round"') if halo else ""
    return under + base.format(fill, "")


def link_color(l):
    if l["color"]:
        return l["color"]
    if not l["insulated"]:
        return "#a8a8a8"
    n = (l["net"] or "").upper()
    if n in ("GND", "0V", "VSS") or n.startswith("GND"):
        return "#222222"
    if re.match(r"^\+?(VCC|VDD|VIN|VBAT|\d+V\d*|3V3|5V)", n):
        return "#d62728"
    return PALETTE[sum(map(ord, n)) % len(PALETTE)]


def render_svg(m, side):
    if side not in ("copper", "component"):
        raise ValueError("side must be copper or component")
    w, h, comp_side, rep = m["w"], m["h"], side == "component", m["report"]

    def X(x):
        return MARGIN + (x if comp_side else w - 1 - x) * PITCH

    def Y(y):
        return TOP + y * PITCH

    def S(p):
        return X(p[0]), Y(p[1])

    def poly(pts, **attrs):
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        return f'<polygon points="{" ".join(f"{fmt(x)},{fmt(y)}" for x, y in map(S, pts))}" {a}/>'

    def rect(box, **attrs):
        (x0, y0), (x1, y1) = S(box[:2]), S(box[2:])
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        return (f'<rect x="{fmt(min(x0, x1))}" y="{fmt(min(y0, y1))}" width="{fmt(abs(x1 - x0))}" '
                f'height="{fmt(abs(y1 - y0))}" {a}/>')

    right, bottom = MARGIN + (w - 1) * PITCH, Y(h - 1)
    W = max(right + MARGIN, 640)
    placed = [(MARGIN - 20, TOP - 42, right + 20, TOP - 24)]          # obstacles for labels: column numbers ...
    if comp_side:                                                     # ... and link wires
        for l in m["links"]:
            (ax, ay), (bx, by) = S(l["a"]), S(l["b"])
            steps = max(1, int(math.hypot(bx - ax, by - ay) // 8))
            placed += [(ax + (bx - ax) * i / steps - 4, ay + (by - ay) * i / steps - 4,
                        ax + (bx - ax) * i / steps + 4, ay + (by - ay) * i / steps + 4) for i in range(steps + 1)]

    def place_label(cands, s, size, **kw):
        """Put a label at the first candidate centre that does not hit an earlier label."""
        tw, th = len(s) * size * 0.6 + 4, size + 4
        def box(cx, cy, rot):
            bw, bh = (th, tw) if rot else (tw, th)
            return (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        for cx, cy, rot in cands:
            r = box(cx, cy, rot)
            if all(r[2] < q[0] or r[0] > q[2] or r[3] < q[1] or r[1] > q[3] for q in placed):
                break
        else:
            cx, cy, rot = cands[0]
            r = box(cx, cy, rot)
        placed.append(r)
        return text(cx, cy + size * 0.35, s, size, rot=-90 if rot else 0, **kw)

    o = [f'<rect x="{MARGIN - 24}" y="{TOP - 24}" width="{right - MARGIN + 48}" height="{bottom - TOP + 48}" rx="8" '
         f'fill="{BOARD}" stroke="#b39360"/>']
    occupied = m["occupied"]
    if comp_side:
        for y in range(h):
            o.append(f'<line x1="{X(0) - 12}" y1="{Y(y)}" x2="{X(w - 1) + 12}" y2="{Y(y)}" stroke="#cfae78" stroke-width="16" opacity=".45"/>')
        for y in range(h):
            for x in range(w):
                o.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="4" fill="#4a3b30"/>')
        # bodies (modules first, they sit highest and cover the most)
        for c in sorted(m["comps"], key=lambda c: c["shape"].get("style") != "module"):
            o += draw_body(c, S, poly, rect, place_label)
        for l in m["links"]:
            (ax, ay), (bx, by), col = S(l["a"]), S(l["b"]), link_color(l)
            if l["insulated"]:
                o.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="#000" stroke-opacity=".35" stroke-width="8" stroke-linecap="round"/>')
            o.append(f'<line class="link" x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{esc(col)}" '
                     f'stroke-width="{5 if l["insulated"] else 2.5}" stroke-linecap="round"/>')
            for x, y in ((ax, ay), (bx, by)):
                o.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{esc(col)}" stroke="#222"/>')
            if l["net"]:
                mx, my = (ax + bx) / 2, (ay + by) / 2
                o.append(place_label([(mx, my, False), (mx + 16, my, False), (mx, my - 12, False)], l["net"], 8,
                                     fill="#111", halo="#fff"))
        for c in m["comps"]:
            square = c["footprint"] in ("header", "dip", "module")
            for p in c["pins"]:
                x, y = S(p["at"])
                if square and p["number"] == "1":
                    o.append(f'<rect class="pin1" x="{x - 5}" y="{y - 5}" width="10" height="10" fill="#f2d94e" stroke="#222" stroke-width="1.5"/>')
                else:
                    o.append(f'<circle cx="{x}" cy="{y}" r="4.5" fill="#f2d94e" stroke="#333"/>')
            for s, pos, d, col in c["labels"]:
                x, y = S(pos)
                if d is None:
                    o.append(text(x + 7, y - 8, s, 8, "#222", "start", halo="#fff"))
                else:
                    halo = "#fff" if col == "#222" else None
                    if abs(d[0]) > abs(d[1]):
                        o.append(text(x + d[0] * 9, y + 2.5, s, 7, col, "start" if d[0] > 0 else "end", halo=halo))
                    else:
                        o.append(text(x, y + (14 if d[1] > 0 else -8), s, 7, col, halo=halo))
    else:
        for seg in m["segments"]:
            y, x0, x1 = seg["y"], seg["from"], seg["to"]
            sx0, sx1 = sorted((X(x0), X(x1)))
            o.append(f'<rect class="{"strip" if seg["used"] else "strip-unused"}" x="{sx0 - 14}" y="{Y(y) - 9}" '
                     f'width="{sx1 - sx0 + 28}" height="18" rx="2" fill="{COPPER if seg["used"] else COPPER_UNUSED}"/>')
            if seg["used"] and seg["net"]:
                room = int((sx1 - sx0 + 28) / 4.9)
                s = seg["net"] if len(seg["net"]) <= room else seg["net"][:max(1, room - 1)] + "~"
                o.append(text(sx0 - 13, Y(y) + 20, s, 8, "#5a2d00" if seg["net"] != "NC" else "#777", "start", cls="netlabel"))
        for y in range(h):
            for x in range(w):
                if (x, y) not in m["hole_cuts"]:
                    o.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="4" fill="#2b211b"/>')
        for p in occupied:
            o.append(f'<circle cx="{X(p[0])}" cy="{Y(p[1])}" r="6.5" fill="#d9d9d9" stroke="#808080"/>')
        for x, y in sorted(m["hole_cuts"]):
            cx, cy = X(x), Y(y)
            o.append(f'<g class="cut-hole"><circle cx="{cx}" cy="{cy}" r="11" fill="{BOARD}" stroke="{CUT_RED}" stroke-width="3"/>'
                     f'<path d="M {cx - 7} {cy - 7} l 14 14 M {cx + 7} {cy - 7} l -14 14" stroke="{CUT_RED}" stroke-width="2.5"/></g>')
        for x, y in sorted(m["between"]):
            cx = (X(x) + X(x + 1)) / 2
            o.append(f'<line class="cut-between" x1="{fmt(cx)}" y1="{Y(y) - 13}" x2="{fmt(cx)}" y2="{Y(y) + 13}" '
                     f'stroke="{CUT_RED}" stroke-width="4" stroke-linecap="round"/>')
        for l in m["links"]:
            (ax, ay), (bx, by) = S(l["a"]), S(l["b"])
            o.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{esc(link_color(l))}" stroke-width="2" '
                     'stroke-dasharray="5 4" opacity=".55"/>')
        for c in m["comps"]:
            o.append(rect(c["bbox"], fill="none", stroke="#5b4a35", stroke_dasharray="4 3", opacity=".45"))
            (x0, y0), (x1, y1) = S(c["bbox"][:2]), S(c["bbox"][2:])
            o.append(text((x0 + x1) / 2, (y0 + y1) / 2 + 3, c["ref"], 9, "#4a3a28", halo="#f3e3c3"))

    # labels round the edge: rows A.., columns 1.. (column 1 is on the right when seen from the copper side)
    for x in range(w):
        o.append(text(X(x), TOP - 30, str(x + 1), 10, "#555"))
        o.append(text(X(x), bottom + 38, str(x + 1), 10, "#555"))
    for y in range(h):
        o.append(text(MARGIN - 36, Y(y) + 4, row_name(y), 10, "#555"))
        o.append(text(right + 36, Y(y) + 4, row_name(y), 10, "#555"))

    title = f"{m['name'] or 'Stripboard'} - {'component side' if comp_side else 'copper side'}"
    sub = ("Seen from the component side. Strips run left-right along each lettered row; column 1 is on the left."
           if comp_side else "Seen from the copper side (board flipped left-right): column 1 is on the RIGHT. Cut where marked in red.")
    errors = len(rep["shorts"]) + len(rep["disconnected"]) + len(rep["nc_conflicts"]) + len(rep["netlist_mismatches"])
    status = ("Check: PASS" if rep["valid"] else f"Check: FAIL ({errors} electrical error(s), see report)") + \
             (f" - {len(rep['warnings'])} warning(s)" if rep["warnings"] else "")
    head = [text(16, 24, title, 16, "#111", "start", "bold"), text(16, 42, sub, 11, "#444", "start"),
            text(16, 58, status, 11, "#1a7f37" if rep["valid"] else CUT_RED, "start", "bold")]

    items = ([("pin", "lead / pin"), ("pin1", "pin 1"), ("wire", "insulated link"), ("bare", "bare link")] if comp_side else
             [("track", "track (net below it)"), ("unused", "unused track"), ("holecut", "hole cut (drill)"),
              ("between", "between-hole cut (knife)"), ("joint", "solder joint"), ("link", "link (other side)")])
    legend, lx, ly = [], 16, bottom + 62
    for kind, label in items:
        width = 34 + len(label) * 6.2 + 18
        if lx + width > W - 8:
            lx, ly = 16, ly + 22
        cx, cy = lx + 13, ly
        legend.append({
            "pin": f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="#f2d94e" stroke="#333"/>',
            "pin1": f'<rect x="{cx - 5}" y="{cy - 5}" width="10" height="10" fill="#f2d94e" stroke="#222" stroke-width="1.5"/>',
            "wire": f'<line x1="{cx - 11}" y1="{cy}" x2="{cx + 11}" y2="{cy}" stroke="#1f77b4" stroke-width="5" stroke-linecap="round"/>',
            "bare": f'<line x1="{cx - 11}" y1="{cy}" x2="{cx + 11}" y2="{cy}" stroke="#a8a8a8" stroke-width="2.5"/>',
            "track": f'<rect x="{cx - 13}" y="{cy - 6}" width="26" height="12" fill="{COPPER}"/>',
            "unused": f'<rect x="{cx - 13}" y="{cy - 6}" width="26" height="12" fill="{COPPER_UNUSED}"/>',
            "holecut": f'<circle cx="{cx}" cy="{cy}" r="8" fill="{BOARD}" stroke="{CUT_RED}" stroke-width="2.5"/>'
                       f'<path d="M {cx - 5} {cy - 5} l 10 10 M {cx + 5} {cy - 5} l -10 10" stroke="{CUT_RED}" stroke-width="2"/>',
            "between": f'<rect x="{cx - 13}" y="{cy - 6}" width="11" height="12" fill="{COPPER}"/><rect x="{cx + 2}" y="{cy - 6}" '
                       f'width="11" height="12" fill="{COPPER}"/><line x1="{cx}" y1="{cy - 9}" x2="{cx}" y2="{cy + 9}" stroke="{CUT_RED}" stroke-width="3.5"/>',
            "joint": f'<circle cx="{cx}" cy="{cy}" r="6" fill="#d9d9d9" stroke="#808080"/>',
            "link": f'<line x1="{cx - 11}" y1="{cy}" x2="{cx + 11}" y2="{cy}" stroke="#1f77b4" stroke-width="2" stroke-dasharray="5 4"/>',
        }[kind])
        legend.append(text(lx + 32, cy + 4, label, 10, "#333", "start"))
        lx += width
    H = ly + 20
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
                      'font-family="Helvetica, Arial, sans-serif">',
                      f"<title>{esc(title)}</title>", f'<rect width="100%" height="100%" fill="#fbfaf6"/>',
                      *head, *o, *legend, "</svg>"])


def draw_body(c, S, poly, rect, place_label):
    s, ref, o = c["shape"], c["ref"], []
    (x0, y0), (x1, y1) = S(c["bbox"][:2]), S(c["bbox"][2:])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = abs(x1 - x0), abs(y1 - y0)
    around = [(cx, min(y0, y1) - 9, False), (cx, max(y0, y1) + 10, False), (max(x0, x1) + 14, cy, False), (min(x0, x1) - 14, cy, False)]
    if s["kind"] == "axial":
        (ax, ay), (bx, by) = s["a"], s["b"]
        d = math.dist(s["a"], s["b"])
        u = ((bx - ax) / d, (by - ay) / d)
        v = (-u[1], u[0])
        mx, my, hl, hw = (ax + bx) / 2, (ay + by) / 2, s["len"] / 2, 0.38

        def at(t, k):
            return (mx + u[0] * t + v[0] * k, my + u[1] * t + v[1] * k)
        (sax, say), (sbx, sby) = S(s["a"]), S(s["b"])
        o.append(f'<line x1="{sax}" y1="{say}" x2="{sbx}" y2="{sby}" stroke="#9a9a9a" stroke-width="2.5"/>')
        o.append(poly([at(-hl, -hw), at(hl, -hw), at(hl, hw), at(-hl, hw)], fill="#3b3b3b" if s["diode"] else "#dcc28f",
                      stroke="#222" if s["diode"] else "#7a6030", stroke_width="1.2"))
        if s.get("band"):
            o.append(poly([at(hl * 0.45, -hw), at(hl * 0.8, -hw), at(hl * 0.8, hw), at(hl * 0.45, hw)], fill="#e6e6e6", **{"class": "band"}))
        label = f"{ref} {c['value']}".strip()
        vertical = bh > bw
        fits = len(label) * 9 * 0.55 <= s["len"] * PITCH
        first = [(cx, cy, vertical)] if fits else []
        side = [(max(x0, x1) + 6 + len(label) * 2.7, cy, False), (min(x0, x1) - 6 - len(label) * 2.7, cy, False)] if vertical else around[:2]
        o.append(place_label(first + side + around, label, 9, fill="#fff" if s["diode"] and fits else "#111",
                             weight="bold", halo=None if fits else "#fff"))
    elif s["kind"] == "radial":
        (rx, ry), r = s["c"], s["r"]
        fill = esc(c["color"] or ("#e8483f" if c["type"].lower() == "led" else "#4a6fa5"))
        if s.get("flat"):
            phi, alpha = math.atan2(s["flat"][1], s["flat"][0]), math.acos(0.8)
            pts = [(rx + r * math.cos(t), ry + r * math.sin(t))
                   for t in (phi + alpha + i * (2 * math.pi - 2 * alpha) / 32 for i in range(33))]
            o.append(poly(pts, fill=fill, fill_opacity=".8", stroke="#333", stroke_width="1.2", **{"class": "led"}))
        else:
            sx, sy = S((rx, ry))
            o.append(f'<circle cx="{fmt(sx)}" cy="{fmt(sy)}" r="{fmt(r * PITCH)}" fill="{fill}" fill-opacity=".8" stroke="#333"/>')
        label = f"{ref} {c['value']}".strip()
        o.append(place_label(around + [(cx, cy, False)], label, 9, fill="#111", weight="bold", halo="#fff"))
    else:
        style = s["style"]
        fill, stroke, tcol = {"header": ("#2b2b2b", "#111", "#fff"), "female": ("#1a1a1a", "#555", "#fff"),
                              "dip": ("#303030", "#111", "#fff"), "module": ("#1f5f8b", "#0e3a57", "#fff"),
                              "tactile": ("#4a4a4a", "#222", "#fff"), "generic": ("#a4b7ab", "#454545", "#111")}[style]
        o.append(rect(c["bbox"], fill=fill, stroke=stroke, rx="4", opacity=".88" if style == "module" else ".95",
                      **{"class": f"body-{style}"}))
        if style == "female":
            for p in c["pins"]:
                sx, sy = S(p["at"])
                o.append(f'<rect x="{sx - 6}" y="{sy - 6}" width="12" height="12" fill="#000" stroke="#777"/>')
        if s.get("notch"):
            nx, ny = S(s["notch"])
            o.append(f'<circle class="notch" cx="{fmt(nx)}" cy="{fmt(ny)}" r="7" fill="{BOARD}" stroke="#111"/>')
        if style == "tactile":
            tx, ty = S(s["c"])
            o.append(f'<circle cx="{fmt(tx)}" cy="{fmt(ty)}" r="{0.6 * PITCH}" fill="#222" stroke="#777"/>')
        label = ref if style != "module" else f"{ref} {c['label'] or c['value']}".strip()
        if style == "dip" and c["value"]:
            label = f"{ref} {c['value']}"
        inside = style in ("module", "dip") and (len(label) * 6.6 < max(bw, bh) - 20)
        cands = ([(cx, cy, bh > bw * 1.3)] if inside else []) + around + [(cx, cy, False)]
        o.append(place_label(cands, label, 11 if style == "module" else 10, fill=tcol if inside else "#111",
                             weight="bold", halo=None if inside else "#fff"))
    return o


# ----------------------------------------------------------------------------- build guide
def footprint_text(c):
    fp, n = c["footprint"], len(c["pins"])
    if fp is None:
        return f"custom ({n} pins)"
    rot = f", rot {c['rotation']}" if c["rotation"] else ""
    s = c["shape"]
    if fp == "axial":
        return f"axial, {round(math.dist(s['a'], s['b']))}-hole span{rot}"
    if fp == "radial":
        return f"radial, pitch {round(math.dist(c['pins'][0]['at'], c['pins'][1]['at']))}{rot}"
    if fp == "header":
        return f"header 1x{n}{' female' if s['style'] == 'female' else ''}{rot}"
    if fp == "dip":
        return f"DIP-{n}{rot}"
    if fp == "module":
        return f"module, {n} pins{rot}"
    return f"tactile 6x6 mm{rot}"


def phase(c):
    fp, t = c["footprint"], c["type"].lower()
    if fp == "axial" or (fp is None and t in LOW_TYPES):
        return 3, 0
    if fp in ("header", "dip") or (fp is None and t in SOCKET_TYPES):
        return 4, 0
    return 5, {"tactile": 0, "radial": 1, "module": 3}.get(fp, 2)


def part_notes(c):
    fp, t, pins = c["footprint"], c["type"].lower(), {p["key"]: p for p in c["pins"]}
    notes = []
    if "K" in pins and "A" in pins:
        if t == "led":
            notes.append(f"K (short leg, flat side) at {hole_name(pins['K']['at'])}")
        else:
            notes.append(f"band (cathode K) at {hole_name(pins['K']['at'])}")
    elif t == "resistor":
        notes.append("either way round")
    if fp == "header":
        notes.append(f"pin 1 ({c['pins'][0]['key']}) at {hole_name(c['pins'][0]['at'])}")
    if fp == "dip":
        notes.append(f"use a socket; notch / pin 1 at {hole_name(c['pins'][0]['at'])}; fit the IC after the meter checks")
    if fp == "module":
        p = c["pins"][0]
        notes.append(f"first pin {p['key']} at {hole_name(p['at'])}; female headers recommended")
    for g in c["bridges"]:
        notes.append(f"pins {'+'.join(p['key'] for p in g)} joined inside the part")
    if fp == "tactile":
        notes.append("check with a meter that the joined pairs are the 3-hole-apart legs; if not, rotate 90")
    return "; ".join(notes)


def holes_text(c):
    ps = c["pins"]
    if len(ps) <= 6:
        return " · ".join(f"{p['key']} {hole_name(p['at'])}" for p in ps)
    return f"{ps[0]['key']} {hole_name(ps[0]['at'])} … {ps[-1]['key']} {hole_name(ps[-1]['at'])} ({len(ps)} pins)"


def cell(s):
    return str(s).replace("|", r"\|")


def build_guide(m, slug):
    rep, w, h = m["report"], m["w"], m["h"]
    title = m["name"] or slug
    out = [f"# {title}: stripboard build guide", "",
           f"Generated by `stripboard.py`. Pictures: `{slug}-component.svg` and `{slug}-copper.svg` (PNG copies if PyMuPDF "
           f"is installed). Full data: `{slug}-report.json`.", ""]
    errors = ([f"short between nets {', '.join(s)}" for s in rep["shorts"]] +
              [f"net {n} is in {k} separate pieces" for n, k in rep["disconnected"].items()] +
              [f"NC pin {c['pin']} ({c['hole']}) touches {', '.join(c['connected_to'])}" for c in rep["nc_conflicts"]] +
              [x["message"] for x in rep["netlist_mismatches"]])
    if rep["valid"]:
        out += ["**Layout check: PASS**" + (" (connectivity also matches the schematic netlist)." if rep["netlist_checked"] else "."), ""]
    else:
        out += ["**Layout check: FAILED. Do not build this layout until these are fixed:**", ""] + [f"- {e}" for e in errors] + [""]
    out += ["## Board", "",
            f"- Size: {w} columns x {h} rows ({w * h} holes, 0.1\" / 2.54 mm pitch, about {w * 2.54:.0f} x {h * 2.54:.0f} mm of holes).",
            f"- Copper strips run along the rows, lettered A-{row_name(h - 1)}. Columns are numbered 1-{w}. A hole is row + column: "
            "A1 is the top-left hole seen from the component side.",
            "- Turned over to the copper side, left and right swap: column 1 is on the RIGHT. The copper picture is drawn that way. "
            "Mark the A1 corner on both faces with a pen before you start.",
            "- Input coordinates are zero-based `[column,row]`, so `[0,0]` is A1.", ""]
    out += ["## Parts", "", "| Ref | Type / value | Footprint | Part / description |", "|---|---|---|---|"]
    for c in m["comps"]:
        tv = " ".join(x for x in (c["type"], c["value"]) if x) or "-"
        desc = " - ".join(x for x in (c["part"], c["description"]) if x) or "-"
        out.append(f"| {cell(c['ref'])} | {cell(tv)} | {footprint_text(c)} | {cell(desc)} |")
    out += ["", "## Build steps", "",
            "Cuts are made on the **copper side**, where column 1 is on the right: use the copper picture and count columns from "
            "the right-hand edge. A hole cut removes the copper round one hole (twist a 3-4 mm drill bit or a spot-face cutter by hand). "
            "A between cut (`B7|B8`) severs the track between two holes (score twice with a sharp knife and lift the sliver out).", "",
            "| Step | Phase | Do | Holes | Notes |", "|---:|---|---|---|---|"]
    n = 0
    for cut in rep["cut_list"]:
        n += 1
        sep = " / ".join(s or "-" for s in cut["separates"])
        what = f"drill-cut hole **{cut['name']}**" if cut["kind"] == "hole" else f"knife-cut between **{cut['name']}**"
        out.append(f"| {n} | 1 cut tracks | {cell(what)} | {cell(cut['name'])} | separates {cell(sep)}{' (auto)' if cut['auto'] else ''} |")
    if not rep["cut_list"]:
        n += 1
        out.append(f"| {n} | 1 cut tracks | no cuts needed | - | - |")
    for i, l in enumerate(rep["link_list"], 1):
        n += 1
        kind = "insulated" if l["insulated"] else "bare wire: keep it straight and clear of other leads"
        colour = f"{l['color']} " if l["color"] else ""
        net = f"net {l['net']}{' (inferred)' if l['net_source'] == 'inferred' else ''}" if l["net"] else "net not stated"
        out.append(f"| {n} | 2 links | {colour}link {i} | {l['from_hole']} → {l['to_hole']} | {net}; {kind} |")
    names = {3: "3 low parts", 4: "4 sockets/headers", 5: "5 taller parts"}
    for c in sorted(m["comps"], key=phase):
        n += 1
        item = " ".join(x for x in (c["ref"], c["value"] or c["type"]) if x)
        out.append(f"| {n} | {names[phase(c)[0]]} | fit {cell(item)} | {cell(holes_text(c))} | {cell(part_notes(c))} |")
    checks = rep["continuity_checks"]
    out += ["", "## Before power: multimeter checks", "",
            "Meter on continuity (beep), board unpowered, ICs and modules out of their sockets.", "", "**Should beep** (probe the first hole, touch each of the others):", ""]
    out += [f"- [ ] **{net}**: " + " · ".join(holes) for net, holes in checks["beep"].items()] or ["- (no net has more than one pin)"]
    out += ["", "**Must NOT beep** (across each cut and between neighbouring strips):", ""]
    out += [f"- [ ] {c['a']} ↔ {c['b']}: {c['nets'][0]} vs {c['nets'][1]} ({c['why']})" for c in checks["no_beep"]] or ["- (none)"]
    out += ["", "## Warnings", ""] + ([f"- {x['message']}" for x in rep["warnings"]] or ["- none"])
    if rep["bridges"]:
        out += ["", "## Internal connections modelled", ""] + [f"- {b['note']} ({', '.join(b['holes'])})" for b in rep["bridges"]]
    out += ["", "A passing check is not a safety certification: confirm pinouts, polarity and part sizes against the datasheets.", ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- outputs and CLI
def generate(data, *, auto_cuts=False, side="copper", cut_style="prefer-hole", netlist=None, netlist_ignore=()):
    """Validate, analyse and render one side. Returns (svg_text, report)."""
    if side not in ("copper", "component"):
        raise ValueError("side must be copper or component")
    m = build(data, auto_cuts=auto_cuts, cut_style=cut_style, netlist=netlist, netlist_ignore=netlist_ignore)
    return render_svg(m, side), m["report"]


def slugify(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def svg_to_png(svg_path, png_path):
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open(str(svg_path))
    doc[0].get_pixmap(matrix=fitz.Matrix(2, 2)).save(str(png_path))
    return True


def write_outputs(m, out_dir, slug):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, png_skipped = [], False
    for side in ("component", "copper"):
        svg_path = out_dir / f"{slug}-{side}.svg"
        svg_path.write_text(render_svg(m, side), encoding="utf-8")
        written.append(str(svg_path))
        png = svg_path.with_suffix(".png")
        if svg_to_png(svg_path, png):
            written.append(str(png))
        else:
            png_skipped = True
    report_path, guide_path = out_dir / f"{slug}-report.json", out_dir / f"{slug}-build.md"
    report_path.write_text(json.dumps(m["report"], indent=2) + "\n", encoding="utf-8")
    guide_path.write_text(build_guide(m, slug), encoding="utf-8", newline="\n")
    return written + [str(report_path), str(guide_path)], png_skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="layout JSON")
    ap.add_argument("--output", type=Path, help="SVG for --side (default: <input>.svg unless --out-dir is given)")
    ap.add_argument("--report", type=Path, help="write the JSON report here")
    ap.add_argument("--side", choices=("copper", "component"), default="copper", help="side drawn to --output")
    ap.add_argument("--auto-cuts", action="store_true", help="add the track cuts needed to separate different nets")
    ap.add_argument("--cut-style", choices=CUT_STYLES, default="prefer-hole",
                    help="auto-cut kind: hole, between (knife), or prefer-hole (hole if one is free, else between)")
    ap.add_argument("--netlist", type=Path, help="KiCad XML netlist to verify the board against")
    ap.add_argument("--netlist-ignore", default="", help="comma-separated refs to skip in the netlist check (off-board parts)")
    ap.add_argument("--out-dir", type=Path, help="write <name>-component/copper .svg/.png, -report.json and -build.md here")
    args = ap.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        netlist = args.netlist.read_text(encoding="utf-8") if args.netlist else None
        ignore = [s.strip() for s in args.netlist_ignore.split(",") if s.strip()]
        m = build(data, auto_cuts=args.auto_cuts, cut_style=args.cut_style, netlist=netlist, netlist_ignore=ignore)
    except (ValueError, KeyError, TypeError, OSError) as e:
        ap.exit(2, f"Error: {e}\n")
    report, written = m["report"], []
    if args.output or not args.out_dir:
        output = args.output or args.input.with_suffix(".svg")
        output.write_text(render_svg(m, args.side), encoding="utf-8")
        written.append(str(output))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        written.append(str(args.report))
    if args.out_dir:
        files, png_skipped = write_outputs(m, args.out_dir, slugify(m["name"]) or slugify(args.input.stem) or "stripboard")
        written += files
        if png_skipped:
            print("PyMuPDF not installed: PNG skipped (pip install pymupdf)")
    summary = {k: report[k] for k in ("valid", "shorts", "disconnected", "nc_conflicts", "netlist_mismatches", "cuts")}
    summary["warnings"] = [x["message"] for x in report["warnings"]]
    print(json.dumps({"written": written, **summary}, indent=2))
    if not report["valid"]:
        ap.exit(1)


if __name__ == "__main__":
    main()
