#!/usr/bin/env python3
"""Stripboard renderer and net-connectivity validator. No external dependencies."""
import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

def generate(data, *, auto_cuts=False, side="copper"):
    if side not in ("copper", "component"):
        raise ValueError("side must be copper or component")
    w, h = data["board"]["columns"], data["board"]["rows"]
    if type(w) is not int or type(h) is not int or not (2 <= w <= 200 and 1 <= h <= 200):
        raise ValueError("Invalid board dimensions")
    def point(p):
        if not isinstance(p, (list, tuple)) or len(p) != 2 or any(type(v) is not int for v in p):
            raise ValueError(f"Invalid coordinate: {p!r}")
        x, y = p
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"Outside board: {p!r}")
        return (x, y)
    occupied, terminals = {}, defaultdict(list)
    comps = data.get("components", [])
    refs = set()
    for c in comps:
        ref = c["ref"]
        if not isinstance(ref, str) or not ref or ref in refs:
            raise ValueError(f"Invalid or duplicated component reference: {ref!r}")
        refs.add(ref)
        if not isinstance(c["pins"], dict) or not c["pins"]:
            raise ValueError(f"{ref}: pins must be a nonempty object")
        for pin, spec in c["pins"].items():
            p = point(spec["at"])
            if p in occupied:
                raise ValueError(f"Occupied hole {p}: {occupied[p]} and {ref}.{pin}")
            occupied[p] = f"{ref}.{pin}"
            net = spec.get("net")
            if net is not None:
                if not isinstance(net, str) or not net:
                    raise ValueError("Net names must be nonempty strings")
                terminals[net].append(p)
    raw_cuts = [point(p) for p in data.get("cuts", [])]
    cuts = set(raw_cuts)
    if len(cuts) != len(raw_cuts):
        raise ValueError("Duplicate track cut")
    if auto_cuts:
        rows = defaultdict(list)
        for net, pts in terminals.items():
            for x, y in pts:
                rows[y].append((x, net))
        for y, pts in rows.items():
            pts.sort()
            for (a, na), (b, nb) in zip(pts, pts[1:]):
                if na != nb and not any((x, y) in cuts for x in range(a + 1, b + 1)):
                    candidates = [x for x in range(a + 1, b) if (x, y) not in occupied]
                    if not candidates:
                        raise ValueError(f"No free cut hole between {na} and {nb} on row {y}")
                    cuts.add((candidates[len(candidates)//2], y))
    if cuts & occupied.keys():
        raise ValueError(f"Track cut on component pin: {cuts & occupied.keys()}")
    links = []
    for link in data.get("links", []):
        a, b = point(link["from"]), point(link["to"])
        if a == b or a in cuts or b in cuts:
            raise ValueError(f"Invalid jumper {a} -> {b}")
        links.append((a, b))
    parent = {}
    def find(p):
        parent.setdefault(p, p)
        if parent[p] != p:
            parent[p] = find(parent[p])
        return parent[p]
    def union(a, b):
        parent[find(a)] = find(b)
    for y in range(h):
        prev = None
        for x in range(w):
            p = (x, y)
            if p in cuts:
                prev = None
                continue
            find(p)
            if prev is not None:
                union(prev, p)
            prev = p
    for a, b in links:
        union(a, b)
    clusters = defaultdict(set)
    for net, pts in terminals.items():
        for p in pts:
            clusters[find(p)].add(net)
    shorts = sorted([sorted(names) for names in clusters.values() if len(names) > 1])
    disconnected = {n: len({find(p) for p in pts}) for n, pts in terminals.items() if len({find(p) for p in pts}) > 1}
    report = {"valid": not shorts and not disconnected, "shorts": shorts, "disconnected": disconnected,
              "cuts": [list(p) for p in sorted(cuts, key=lambda p: (p[1], p[0]))],
              "links": len(links), "terminals": sum(map(len, terminals.values()))}
    pitch, margin = 32, 48
    px = lambda x: margin + (x if side == "component" else w - 1 - x) * pitch
    py = lambda y: margin + y * pitch
    tw, th = margin * 2 + (w - 1) * pitch, margin * 2 + (h - 1) * pitch
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="{th}" viewBox="0 0 {tw} {th}">',
           f'<title>Stripboard {side} side; coordinates from component side</title>',
           '<rect width="100%" height="100%" fill="#e0c38f"/>']
    if side == "copper":
        for y in range(h):
            svg.append(f'<line x1="{px(0)}" y1="{py(y)}" x2="{px(w-1)}" y2="{py(y)}" stroke="#ae7035" stroke-width="13"/>')
    for y in range(h):
        for x in range(w):
            svg.append(f'<circle cx="{px(x)}" cy="{py(y)}" r="5" fill="#3d3028" stroke="#fff2ce"/>')
    if side == "copper":
        for x, y in sorted(cuts):
            svg.append(f'<circle cx="{px(x)}" cy="{py(y)}" r="11" fill="#e0c38f" stroke="#df2222" stroke-width="3"/>')
            svg.append(f'<path d="M {px(x)-7} {py(y)-7} l 14 14 M {px(x)+7} {py(y)-7} l -14 14" stroke="#df2222" stroke-width="2"/>')
    for a, b in links:
        svg.append(f'<path d="M {px(a[0])} {py(a[1])} L {px(b[0])} {py(b[1])}" fill="none" stroke="#1875c9" stroke-width="4"/>')
    if side == "component":
        for c in comps:
            pts = [point(e["at"]) for e in c["pins"].values()]
            if len(pts) >= 2:
                a, b = pts[0], pts[-1]
                x1, x2, y1, y2 = px(a[0]), px(b[0]), py(a[1]), py(b[1])
                fill = {"resistor": "#d9bf91", "led": "#7cc9ec", "diode": "#7cc9ec"}.get(c.get("type", "").lower(), "#a4b7ab")
                svg.append(f'<rect x="{min(x1,x2)-9}" y="{min(y1,y2)-9}" width="{abs(x1-x2)+18}" height="{abs(y1-y2)+18}" rx="6" fill="{fill}" stroke="#454545" opacity=".9"/>')
                svg.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2-12}" text-anchor="middle" font-size="12" font-weight="bold">{html.escape(str(c["ref"]))}</text>')
    for c in comps:
        for pin, spec in c["pins"].items():
            x, y = point(spec["at"])
            svg.append(f'<circle cx="{px(x)}" cy="{py(y)}" r="6" fill="#fff077" stroke="#222"/>')
            svg.append(f'<text x="{px(x)+7}" y="{py(y)-9}" font-size="10">{html.escape(str(c["ref"])+"."+str(pin))}</text>')
    for x in range(w):
        svg.append(f'<text x="{px(x)}" y="23" text-anchor="middle" font-size="11">{x}</text>')
    for y in range(h):
        svg.append(f'<text x="20" y="{py(y)+4}" font-size="11">{y}</text>')
    svg.append('</svg>')
    return "\n".join(svg), report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--auto-cuts", action="store_true")
    ap.add_argument("--side", choices=("copper", "component"), default="copper")
    args = ap.parse_args()
    try:
        svg, report = generate(json.loads(args.input.read_text()), auto_cuts=args.auto_cuts, side=args.side)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        ap.exit(2, f"Error: {e}\n")
    output = args.output or args.input.with_suffix(".svg")
    output.write_text(svg)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"svg": str(output), **report}, indent=2))
    if not report["valid"]:
        ap.exit(1)
if __name__ == "__main__":
    main()
