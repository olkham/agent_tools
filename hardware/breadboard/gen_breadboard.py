#!/usr/bin/env python3
"""Breadboard plan for the dev-board build (DOIT ESP32 DevKit V1 + the BOM-farnell.csv parts).

Outputs (next to this file):
  devboard-breadboard.svg   top view of an 830-point breadboard with every part and jumper
  devboard-breadboard.png   the same, rasterised (needs PyMuPDF; skipped if it is missing)
  devboard-breadboard.md    build steps: every lead and wire, hole by hole

The placement below is checked before anything is drawn:
  * every lead and wire end sits in a real, free hole (rail holes come in groups of 5);
  * the connectivity the breadboard makes (5-hole strips, rails, jumpers, the dev board's own GND tie)
    is exactly the intended netlist NETS: nothing missing, no unintended merges, unused dev-board pins
    left alone.  Rails are treated as split in the middle (the worst case), so the plan also works on
    breadboards whose rails are continuous;
  * upright parts (LEDs, capacitors, transistor, receiver) do not cover another part's hole.

Breadboard model: rows 1..63 along the length, columns a-e | channel | f-j, two rails on each long side
(outer = +, inner = -).  The board is drawn landscape: row 1 on the left, the j-side rails at the top.

Stdlib only (PNG via PyMuPDF if installed).  Usage: python3 gen_breadboard.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'devboard-breadboard')

# ------------------------------------------------------------------------------------------- breadboard
ROWS = 63
COLS = 'abcdefghij'
COL_Y = {'j': 3, 'i': 4, 'h': 5, 'g': 6, 'f': 7, 'e': 10, 'd': 11, 'c': 12, 'b': 13, 'a': 14}  # pitches
RAIL_Y = {'top+': 0, 'top-': 1, 'bot-': 16, 'bot+': 17}
RAIL_NAME = {'top+': 'j-side + rail', 'top-': 'j-side - rail', 'bot-': 'a-side - rail', 'bot+': 'a-side + rail'}
RAIL_P = [2 + k + k // 5 for k in range(50)]   # rail hole positions, in rows-1 (groups of 5, gaps between)
RAIL_SPLIT = 31                                # gap in the middle where split rails are cut


def half(col):
    return 'L' if col in 'abcde' else 'R'


# ------------------------------------------------------------------------------------------- the build
# DOIT ESP32 DevKit V1, 30 pins, 0.9" between the pin rows: straddles the channel with its pins in columns b
# and i, USB toward row 1 (off the end of the board), antenna toward row 15+.  Pin order (USB end first):
DEV_B = ['3V3', 'GND', 'D15', 'D2', 'D4', 'RX2', 'TX2', 'D5', 'D18', 'D19', 'D21', 'RX0', 'TX0', 'D22', 'D23']
DEV_I = ['VIN', 'GND', 'D13', 'D12', 'D14', 'D27', 'D26', 'D25', 'D33', 'D32', 'D35', 'D34', 'VN', 'VP', 'EN']

# Parts: ref -> (kind, value, {pin: hole}, extra).  A hole is ('a'..'j', row) or (rail, row-ish position).
PARTS = {
    'DEV': ('devkit', 'DOIT ESP32 DevKit V1',
            dict([('%s_b' % n if n == 'GND' else n, ('b', r + 1)) for r, n in enumerate(DEV_B)] +
                 [('%s_i' % n if n == 'GND' else n, ('i', r + 1)) for r, n in enumerate(DEV_I)]), {}),
    # IR transmitter (j-side half): two strings of two TSAL6200, 15 ohm each, BC337-40 low-side switch
    'Q1': ('to92', 'BC337-40', {'C': ('j', 30), 'B': ('j', 31), 'E': ('j', 32)}, {'flat': 'down'}),
    'R1': ('res', '220R', {'1': ('d', 31), '2': ('g', 31)}, {'w': 0.25}),
    'R2': ('res', '15R', {'1': ('f', 30), '2': ('f', 25)}, {'w': 1}),
    'R3': ('res', '15R', {'1': ('h', 30), '2': ('h', 35)}, {'w': 1}),
    'D1': ('led', 'TSAL6200', {'A': ('f', 23), 'K': ('f', 24)}, {}),
    'D2': ('led', 'TSAL6200', {'A': ('i', 24), 'K': ('i', 25)}, {}),
    'D3': ('led', 'TSAL6200', {'A': ('h', 37), 'K': ('h', 36)}, {}),
    'D4': ('led', 'TSAL6200', {'A': ('f', 36), 'K': ('f', 35)}, {}),
    'C2': ('ecap', '220uF', {'+': ('top+', 29), '-': ('top-', 29)}, {'d': 8}),
    # IR receiver (a-side half), facing the channel; supply filter + pull-up straight from the a-side rails
    'U1': ('tsop', 'TSOP38238', {'VS': ('b', 44), 'GND': ('b', 45), 'OUT': ('b', 46)}, {'face': 'up'}),
    'C1': ('ecap', '4.7uF', {'+': ('e', 44), '-': ('e', 45)}, {'d': 5}),
    'R4': ('res', '100R', {'1': ('bot+', 41), '2': ('a', 44)}, {'w': 0.25}),
    'R5': ('res', '10k', {'1': ('bot+', 49), '2': ('a', 46)}, {'w': 0.25}),
}

# Jumpers: (name, colour key, from, to, waypoints in (row, y-pitch), note)
WIRES = [
    ('W1', '3v3', ('a', 1), ('bot+', 3), [], '3V3 to the a-side + rail'),
    ('W2', 'gnd', ('a', 2), ('bot-', 4), [], 'GND to the a-side - rail'),
    ('W3', '5v', ('j', 1), ('top+', 3), [], 'VIN (USB 5 V) to the j-side + rail'),
    ('W4', 'gnd', ('j', 2), ('top-', 4), [], 'GND to the j-side - rail'),
    ('W5', 'gpio4', ('a', 5), ('a', 31), [(5.2, 14.55), (30.8, 14.55)], 'GPIO4 to the base resistor row'),
    ('W6', '5v', ('j', 23), ('top+', 23), [], '5 V to LED string 1 (D1 anode)'),
    ('W7', '5v', ('j', 37), ('top+', 37), [], '5 V to LED string 2 (D3 anode)'),
    ('W8', 'gnd', ('i', 32), ('top-', 35), [], 'Q1 emitter to GND'),
    ('W9', 'gnd', ('a', 45), ('bot-', 45), [], 'receiver GND'),
    ('W10', 'gpio34', ('j', 12), ('e', 46), [(11.6, 2.25), (19.0, 2.25), (19.6, 8.5), (44.4, 8.5)], 'GPIO34 to the receiver OUT row: round the antenna end, then along the channel'),
    # rail bridges: only needed on breadboards whose rails are split in the middle (harmless otherwise)
    ('B1', 'bridge5', ('top+', 31), ('top+', 33), [], 'bridge the j-side + rail (split rails only)'),
    ('B2', 'bridgeg', ('top-', 31), ('top-', 33), [], 'bridge the j-side - rail (split rails only)'),
    ('B3', 'bridgeg', ('bot-', 31), ('bot-', 33), [], 'bridge the a-side - rail (split rails only)'),
    ('B4', 'bridge3', ('bot+', 31), ('bot+', 33), [], 'bridge the a-side + rail (split rails only)'),
]

# Intended connectivity (REF.PIN).  Dev-board pins not listed must stay unconnected.
NETS = {
    '5V': ['DEV.VIN', 'D1.A', 'D3.A', 'C2.+'],
    'GND': ['DEV.GND_b', 'DEV.GND_i', 'Q1.E', 'U1.GND', 'C1.-', 'C2.-'],
    '3V3': ['DEV.3V3', 'R4.1', 'R5.1'],
    'GPIO4': ['DEV.D4', 'R1.1'],
    'BASE': ['R1.2', 'Q1.B'],
    'COLLECTOR': ['Q1.C', 'R2.1', 'R3.1'],
    'S1_BOTTOM': ['R2.2', 'D2.K'],
    'S1_MID': ['D2.A', 'D1.K'],
    'S2_BOTTOM': ['R3.2', 'D4.K'],
    'S2_MID': ['D4.A', 'D3.K'],
    'GPIO34': ['DEV.D34', 'U1.OUT', 'R5.2'],
    'TSOP_VS': ['U1.VS', 'R4.2', 'C1.+'],
}
INTERNAL = [('DEV.GND_b', 'DEV.GND_i')]   # tied together on the dev board itself

COLOURS = {'5v': '#d62728', '3v3': '#ff8c1a', 'gnd': '#222222', 'gpio4': '#1f6fd1', 'gpio34': '#2a9d3a',
           'bridge5': '#d62728', 'bridge3': '#ff8c1a', 'bridgeg': '#222222'}
LEGEND = [('5v', '5 V (VIN)'), ('3v3', '3V3'), ('gnd', 'GND'), ('gpio4', 'GPIO4 (IR TX)'), ('gpio34', 'GPIO34 (IR RX)')]
BANDS = {'0': '#000000', '1': '#8b4513', '2': '#e02020', '3': '#ff8c00', '4': '#f5d000', '5': '#2e9e3a',
         '6': '#1f5fd1', '7': '#8a2be2', '8': '#808080', '9': '#ffffff'}


# ------------------------------------------------------------------------------------------- geometry
def resolve(hole, used):
    """('c', row) -> itself; (rail, near_row) -> the nearest free rail hole as (rail, position)."""
    if hole[0] in RAIL_Y:
        rail, near = hole
        for p in sorted(RAIL_P, key=lambda p: (abs(p - (near - 1)), p)):
            if (rail, p) not in used:
                return (rail, p)
        raise ValueError('rail %s full' % rail)
    col, row = hole
    assert col in COLS and 1 <= row <= ROWS, hole
    return hole


def xy(hole):
    """Hole -> (x, y) in pitches: x = row - 1 (or rail position), y = column/rail line."""
    if hole[0] in RAIL_Y:
        return float(hole[1]), float(RAIL_Y[hole[0]])
    return float(hole[1] - 1), float(COL_Y[hole[0]])


def node(hole):
    if hole[0] in RAIL_Y:
        return (hole[0], 0 if hole[1] < RAIL_SPLIT else 1)
    return (half(hole[0]), hole[1])


def hole_name(hole):
    if hole[0] in RAIL_Y:
        return '%s (by row %d)' % (RAIL_NAME[hole[0]], hole[1] + 1)
    return '%s%d' % hole


# ------------------------------------------------------------------------------------------- checks
def build():
    used, legs, wires, errors = {}, {}, [], []
    for ref, (kind, value, pins, extra) in PARTS.items():
        for pin, h in pins.items():
            h = resolve(h, used)
            if h in used:
                errors.append('%s.%s: hole %s already holds %s' % (ref, pin, hole_name(h), used[h]))
            used[h] = '%s.%s' % (ref, pin)
            legs['%s.%s' % (ref, pin)] = h
    for name, colour, a, b, via, note in WIRES:
        ends = []
        for end in (a, b):
            h = resolve(end, used)
            if h in used:
                errors.append('%s: hole %s already holds %s' % (name, hole_name(h), used[h]))
            used[h] = name
            ends.append(h)
        wires.append((name, colour, ends[0], ends[1], via, note))
    # connectivity: union-find over breadboard nodes, joined by wires and part-internal ties
    parent = {}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a, b):
        parent[find(a)] = find(b)

    for name, colour, a, b, via, note in wires:
        union(node(a), node(b))
    for p, q in INTERNAL:
        union(node(legs[p]), node(legs[q]))
    groups = {}
    for pin, h in legs.items():
        groups.setdefault(find(node(h)), set()).add(pin)
    where = {pin: find(node(h)) for pin, h in legs.items()}
    intended = set()
    for net, pins in NETS.items():
        intended |= set(pins)
        roots = {where[p] for p in pins}
        if len(roots) > 1:
            errors.append('net %s is split: %s' % (net, sorted(sorted(groups[r]) for r in roots)))
        extra_pins = groups[where[pins[0]]] - set(pins)
        if extra_pins:
            errors.append('net %s also reaches %s' % (net, sorted(extra_pins)))
    for pin in legs:
        if pin not in intended and len(groups[where[pin]]) > 1:
            errors.append('%s should be unconnected but meets %s' % (pin, sorted(groups[where[pin]] - {pin})))
    # upright bodies must not cover another part's hole
    for ref, (kind, value, pins, extra) in PARTS.items():
        r = {'led': 1.15, 'ecap': extra.get('d', 5) / 2.54 / 2, 'to92': 0.95}.get(kind)
        if r is None:
            continue
        cx, cy = body_centre(ref, legs)
        for h, who in used.items():
            if who.split('.')[0] == ref or (kind == 'ecap' and h[0] in RAIL_Y):
                continue
            x, y = xy(h)
            if math.hypot(x - cx, y - cy) < r:
                errors.append('%s body covers hole %s (%s)' % (ref, hole_name(h), who))
    # upright bodies must not collide with each other (LED bodies 5 mm, flanges may touch)
    bodies = [(ref, body_centre(ref, legs), {'led': 5.0, 'ecap': extra.get('d', 5), 'to92': 4.8}[kind] / 2.54 / 2)
              for ref, (kind, value, pins, extra) in PARTS.items() if kind in ('led', 'ecap', 'to92')]
    for i, (ra, (xa, ya), rra) in enumerate(bodies):
        for rb, (xb, yb), rrb in bodies[i + 1:]:
            if math.hypot(xa - xb, ya - yb) < rra + rrb:
                errors.append('%s and %s bodies collide' % (ra, rb))
    return legs, wires, errors


def body_centre(ref, legs):
    pts = [xy(h) for p, h in legs.items() if p.split('.')[0] == ref]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


# ------------------------------------------------------------------------------------------- drawing
P = 22.0                         # px per 0.1" pitch
MX, MY = 3.4 * P, 2.6 * P        # board origin on the canvas
BB_X0, BB_X1 = -1.2, ROWS - 1 + 1.2
BB_Y0, BB_Y1 = -1.3, 18.3
W = MX + (BB_X1 + 1.6) * P
H_BOARD = MY + (BB_Y1 + 0.8) * P


def X(x):
    return MX + x * P


def Y(y):
    return MY + y * P


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def text(x, y, s, size=11, fill='#333', anchor='middle', weight='normal', halo=False, rot=0, family='sans'):
    fam = {'sans': 'Helvetica, Arial, sans-serif', 'mono': 'Consolas, Menlo, monospace'}[family]
    tr = ' transform="rotate(%g %.1f %.1f)"' % (rot, x, y) if rot else ''
    one = ('<text x="%.1f" y="%.1f" font-family="%s" font-size="%g" fill="%%s" text-anchor="%s" font-weight="%s"%%s%s>'
           '%s</text>' % (x, y, fam, size, anchor, weight, tr, esc(s)))
    under = one % ('#ffffff', ' stroke="#ffffff" stroke-width="3.2" stroke-linejoin="round"') if halo else ''
    return under + one % (fill, '')


def draw_breadboard(o):
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="#f4f2ec" stroke="#cfcab9" '
             'stroke-width="1.5"/>' % (X(BB_X0), Y(BB_Y0), (BB_X1 - BB_X0) * P, (BB_Y1 - BB_Y0) * P, 0.6 * P))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#e4e0d4"/>'
             % (X(BB_X0 + 0.3), Y(8.05), (BB_X1 - BB_X0 - 0.6) * P, 0.9 * P))          # centre channel
    for rail, y in RAIL_Y.items():
        colour = '#d62728' if rail.endswith('+') else '#1f5fbf'
        ly = y - 0.55 if rail in ('top+', 'bot-') else y + 0.55
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6"/>'
                 % (X(0.5), Y(ly), X(ROWS - 1.5), Y(ly), colour))
        sign = '+' if rail.endswith('+') else '−'
        for x in (-0.6, ROWS - 0.4):
            o.append(text(X(x), Y(y) + 4, sign, 13, colour, weight='bold'))
        for p in RAIL_P:
            o.append(hole_svg(p, y))
    for col, y in COL_Y.items():
        for r in range(1, ROWS + 1):
            o.append(hole_svg(r - 1, y))
        for x in (-0.6, ROWS - 0.4):
            o.append(text(X(x), Y(y) + 4, col, 10, '#8a8573'))
    for r in [1] + list(range(5, ROWS, 5)) + [ROWS]:
        for y in (2.05, 9.15, 15.25):
            o.append(text(X(r - 1), Y(y) + 3.5, str(r), 8.5, '#8a8573'))


def hole_svg(x, y):
    s = 0.34 * P
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1" fill="#55524a"/>' % (X(x) - s / 2, Y(y) - s / 2, s, s)


def draw_devkit(o, legs):
    # 51.8 x 28.2 mm board: USB end 5 mm before row 1, antenna end ~11 mm past row 15
    x0, x1 = -5.0 / 2.54, 14 + 11.2 / 2.54
    yc, hh = 8.5, 28.2 / 2.54 / 2
    o.append('<g opacity="0.96">')
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" fill="#1d2a4f" stroke="#0e1529" '
             'stroke-width="1.2"/>' % (X(x0), Y(yc - hh), (x1 - x0) * P, 2 * hh * P))
    # USB connector, buttons, module can + antenna
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="#c7cad1" stroke="#80838a"/>'
             % (X(x0 - 0.45), Y(yc - 1.5), 2.4 * P, 3.0 * P))
    for bx, label in ((x0 + 3.0, 'EN'), (x0 + 3.0, 'BOOT')):
        pass
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="#d9dbe0" stroke="#9a9ca3"/>'
             % (X(6.6), Y(yc - 3.55), 6.9 * P, 7.1 * P))
    o.append(text(X(10.05), Y(yc - 0.3), 'ESP32-WROOM-32', 10, '#4a4d55'))
    o.append(text(X(10.05), Y(yc + 0.9), 'module', 9, '#6a6d75'))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#26375f" stroke="#3b4f80"/>'
             % (X(13.5), Y(yc - 3.55), 2.55 * P, 7.1 * P))
    zz = ' '.join('%.1f,%.1f' % (X(13.9 + 0.55 * (k % 2) + 0.75 * (k // 2) * 0), Y(yc - 3.0 + 0.55 * k))
                  for k in range(11))
    o.append('<polyline points="%s" fill="none" stroke="#c9a54a" stroke-width="2"/>' % zz)
    o.append(text(X(14.8), Y(yc + 3.25), 'antenna', 8, '#9fb0d8'))
    for k, (bx, label) in enumerate(((1.4, 'EN'), (1.4, 'BOOT'))):
        by = yc - 2.1 if k == 0 else yc + 2.1
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1" fill="#e9e9e9" stroke="#999"/>'
                 % (X(bx) - 0.6 * P, Y(by) - 0.6 * P, 1.2 * P, 1.2 * P))
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#444"/>' % (X(bx), Y(by), 0.35 * P))
        o.append(text(X(bx + 1.2), Y(by) + 3.5, label, 8, '#cfd6ea', anchor='start'))
    o.append(text(X(x0 + 0.1), Y(yc - 2.6), 'USB', 9, '#cfd6ea', anchor='start'))
    o.append(text(X(4.0), Y(yc - 2.6), 'GPIO2 LED', 7.5, '#9fd0ff', anchor='middle'))
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#4da3ff"/>'
             % (X(3.6), Y(yc - 2.2), 0.8 * P, 0.45 * P))
    # header pins + labels
    for pin, h in legs.items():
        if not pin.startswith('DEV.'):
            continue
        x, y = xy(h)
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#111"/>'
                 % (X(x) - 0.45 * P, Y(y) - 0.45 * P, 0.9 * P, 0.9 * P))
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#d8b64a"/>' % (X(x), Y(y), 0.22 * P))
        name = pin.split('.')[1].split('_')[0]
        hot = name in ('3V3', 'GND', 'VIN', 'D4', 'D34')
        ly = y + 1.05 if y > 8.5 else y - 0.85
        o.append(text(X(x), Y(ly) + 3, name, 7.5 if not hot else 8, '#ffe28a' if hot else '#aeb8d6',
                      weight='bold' if hot else 'normal', rot=-90 if False else 0))
    o.append('</g>')


def draw_resistor(o, ref, value, a, b, w):
    (x1, y1), (x2, y2) = xy(a), xy(b)
    L = math.hypot(x2 - x1, y2 - y1)
    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    bl = (9.0 if w >= 1 else 6.3) / 2.54
    bw = (3.3 if w >= 1 else 2.4) / 2.54
    bl = min(bl, L - 0.5)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#9a9a9a" stroke-width="2" stroke-linecap="round"/>'
             % (X(x1), Y(y1), X(x2), Y(y2)))
    for x, y in ((x1, y1), (x2, y2)):
        o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="#7d7d7d"/>' % (X(x), Y(y)))
    g = '<g transform="translate(%.1f %.1f) rotate(%.2f)">' % (X(cx), Y(cy), ang)
    g += '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="%s" stroke="#9c8656" stroke-width="0.8"/>' % (
        -bl * P / 2, -bw * P / 2, bl * P, bw * P, bw * P / 2.4, '#e9d3a3' if w < 1 else '#dcc39a')
    digits, mult = bands(value)
    cols = [BANDS[digits[0]], BANDS[digits[1]], BANDS[str(mult)], '#c9a227']
    for k, c in enumerate(cols):
        bx = -bl * P / 2 + bl * P * (0.2 + 0.17 * k + (0.08 if k == 3 else 0))
        g += '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (bx, -bw * P / 2, 0.11 * bl * P, bw * P, c)
    g += '</g>'
    o.append(g)
    return cx, cy, ang


def bands(value):
    v = value.rstrip('R')
    mult_k = 1000 if v.endswith('k') else 1
    n = float(v.rstrip('k')) * mult_k
    digits = '%d' % round(n)
    s = digits[:2] if len(digits) >= 2 else digits + '0'
    exp = len(digits) - 2 if len(digits) >= 2 else -1
    return s, exp


def draw_led(o, ref, legs):
    a, k = xy(legs[ref + '.A']), xy(legs[ref + '.K'])
    cx, cy = (a[0] + k[0]) / 2, (a[1] + k[1]) / 2
    ang = math.degrees(math.atan2(k[1] - a[1], k[0] - a[0]))   # +x of the group points at the cathode
    r = 5.8 / 2.54 / 2 * P
    g = '<g transform="translate(%.1f %.1f) rotate(%.2f)">' % (X(cx), Y(cy), ang)
    g += '<path d="M %.1f %.1f A %.1f %.1f 0 1 0 %.1f %.1f Z" fill="#9fc2ec" fill-opacity="0.9" stroke="#4f7fb8" stroke-width="1"/>' % (
        r * 0.82, -r * 0.57, r, r, r * 0.82, r * 0.57)
    g += '<circle cx="0" cy="0" r="%.1f" fill="#c6dcf6" stroke="#6d98cc" stroke-width="0.8"/>' % (r * 0.78)
    g += '</g>'
    o.append(g)
    for (x, y), lab in ((a, '+'), (k, '')):
        o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="#7d7d7d"/>' % (X(x), Y(y)))
    o.append(text(X(a[0]) + (-7 if a[0] < k[0] else 7), Y(a[1]) + 4, '+', 10, '#c0392b', weight='bold', halo=True))
    return cx, cy


def draw_ecap(o, ref, value, legs, d):
    p, m = xy(legs[ref + '.+']), xy(legs[ref + '.-'])
    cx, cy = (p[0] + m[0]) / 2, (p[1] + m[1]) / 2
    r = d / 2.54 / 2 * P
    ang = math.degrees(math.atan2(m[1] - p[1], m[0] - p[0]))
    g = '<g transform="translate(%.1f %.1f) rotate(%.2f)">' % (X(cx), Y(cy), ang)
    g += '<circle cx="0" cy="0" r="%.1f" fill="#1c2f5e" stroke="#0d1838" stroke-width="1"/>' % r
    g += '<path d="M %.1f %.1f A %.1f %.1f 0 0 1 %.1f %.1f Z" fill="#c9d3ea"/>' % (r * 0.45, -r * 0.89, r, r, r * 0.45, r * 0.89)
    g += '</g>'
    o.append(g)
    o.append(text(X(cx), Y(cy) + 3.5, '−', 10, '#1c2f5e', halo=False) if False else '')
    return cx, cy


def draw_to92(o, ref, legs):
    pts = [xy(legs[ref + '.' + p]) for p in 'CBE']
    cx = sum(p[0] for p in pts) / 3
    cy = sum(p[1] for p in pts) / 3
    w, d = 4.8 / 2.54 * P, 3.8 / 2.54 * P
    # flat face toward the channel (+y), round side toward the rails (-y)
    path = 'M %.1f %.1f L %.1f %.1f A %.1f %.1f 0 0 0 %.1f %.1f Z' % (
        X(cx) - w / 2, Y(cy) + 0.3 * d, X(cx) + w / 2, Y(cy) + 0.3 * d, w / 2, d * 0.75, X(cx) - w / 2, Y(cy) + 0.3 * d)
    o.append('<path d="%s" fill="#202020" stroke="#000" stroke-width="1"/>' % path)
    for p, (x, y) in zip('CBE', pts):
        o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="#9a9a9a"/>' % (X(x), Y(y)))
        o.append(text(X(x), Y(y) - 0.42 * P, p, 7, '#ffffff', weight='bold'))
    return cx, cy


def draw_tsop(o, ref, legs):
    pts = [xy(legs[ref + '.' + p]) for p in ('VS', 'GND', 'OUT')]
    cx = sum(p[0] for p in pts) / 3
    cy = pts[0][1]
    w = 6.0 / 2.54 * P
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="#1a1a1a" stroke="#000"/>'
             % (X(cx) - w / 2, Y(cy) - 0.75 * P, w, 1.25 * P))
    o.append('<path d="M %.1f %.1f A %.1f %.1f 0 0 1 %.1f %.1f Z" fill="#3a3a3a" stroke="#000"/>'
             % (X(cx) - 0.75 * P, Y(cy) - 0.75 * P, 0.75 * P, 0.6 * P, X(cx) + 0.75 * P, Y(cy) - 0.75 * P))
    for p, (x, y) in zip(('VS', 'GND', 'OUT'), pts):
        o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="#9a9a9a"/>' % (X(x), Y(y)))
        o.append(text(X(x), Y(y) + 0.95 * P, p if p != 'GND' else 'G', 7.5, '#555', halo=True))
    return cx, cy


def wire_path(a, b, via):
    pts = [xy(a)] + list(via) + [xy(b)]
    pts = [(X(x), Y(y)) for x, y in pts]
    if len(pts) == 2:
        (x1, y1), (x2, y2) = pts
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1
        bow = min(0.6 * P, 0.18 * L)
        mx, my = (x1 + x2) / 2 - dy / L * bow, (y1 + y2) / 2 + dx / L * bow
        return 'M %.1f %.1f Q %.1f %.1f %.1f %.1f' % (x1, y1, mx, my, x2, y2)
    d = 'M %.1f %.1f' % pts[0]
    for k in range(1, len(pts) - 1):
        (xa, ya), (xb, yb), (xc, yc) = pts[k - 1], pts[k], pts[k + 1]
        r = 0.6 * P
        la, lc = math.hypot(xb - xa, yb - ya) or 1, math.hypot(xc - xb, yc - yb) or 1
        p1 = (xb - (xb - xa) / la * min(r, la / 2), yb - (yb - ya) / la * min(r, la / 2))
        p2 = (xb + (xc - xb) / lc * min(r, lc / 2), yb + (yc - yb) / lc * min(r, lc / 2))
        d += ' L %.1f %.1f Q %.1f %.1f %.1f %.1f' % (p1[0], p1[1], xb, yb, p2[0], p2[1])
    d += ' L %.1f %.1f' % pts[-1]
    return d


def draw_wire(o, name, colour, a, b, via):
    d = wire_path(a, b, via)
    c = COLOURS[colour]
    bridge = colour.startswith('bridge')
    dash, cap, wd = ('', 'round', 0.16 * P) if bridge else ('', 'round', 0.42 * P)
    if not bridge:
        o.append('<path d="%s" fill="none" stroke="#000" stroke-opacity="0.35" stroke-width="%.1f" stroke-linecap="round"/>'
                 % (d, wd + 2))
    o.append('<path d="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linecap="%s"%s/>' % (d, c, wd, cap, dash))
    for h in (a, b):
        x, y = xy(h)
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="#000" stroke-opacity="0.5"/>'
                 % (X(x), Y(y), (0.16 if bridge else 0.26) * P, c))


def svg(legs, wires):
    o = []
    rows_txt = 9
    notes = [
        'Check first: the DOIT board’s pin rows must be 0.9" (22.86 mm) apart so it leaves column a and column j free.',
        'A board with 1.0" rows covers one side completely: use two breadboards side by side or jumper leads.',
        'Rails: outer = +, inner = − as drawn. Follow your board’s red/blue markings. The thin bridges are only needed if',
        'the rails are split in the middle. LEDs: long leg (+) = anode. Q1: flat face toward the channel. U1 dome faces the channel.',
        'Electrolytics: the stripe marks −. Bend the IR LEDs toward what you want to control and splay the two strings.',
    ]
    leg_h = 46 + rows_txt + len(notes) * 15
    Ht = H_BOARD + leg_h
    o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
             % (W, Ht, W, Ht))
    o.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    o.append(text(MX + BB_X0 * P, 26, 'IR Blaster node — breadboard build (DOIT ESP32 DevKit V1 + BOM-farnell.csv parts)',
                  16, '#222', anchor='start', weight='bold'))
    o.append(text(MX + BB_X0 * P, 44, 'Generated by hardware/breadboard/gen_breadboard.py; connectivity checked against the '
                  'intended netlist. Step-by-step holes: %s.md' % os.path.basename(OUT), 11, '#666', anchor='start'))
    draw_breadboard(o)
    draw_devkit(o, legs)
    labels = []
    for ref, (kind, value, pins, extra) in PARTS.items():
        a = {p: legs['%s.%s' % (ref, p)] for p in pins}
        if kind == 'res':
            cx, cy, ang = draw_resistor(o, ref, value, a['1'], a['2'], extra['w'])
            labels.append((ref, value.replace('R', 'Ω').replace('k', 'kΩ') if value != '15R' else '15Ω 1W',
                           cx, cy, ang))
        elif kind == 'led':
            cx, cy = draw_led(o, ref, legs)
            labels.append((ref, 'IR', cx, cy, None))
        elif kind == 'ecap':
            cx, cy = draw_ecap(o, ref, value, legs, extra['d'])
            labels.append((ref, value.replace('u', 'µ'), cx, cy, None))
        elif kind == 'to92':
            cx, cy = draw_to92(o, ref, legs)
            labels.append((ref, value, cx, cy, 'to92'))
        elif kind == 'tsop':
            cx, cy = draw_tsop(o, ref, legs)
            labels.append((ref, value, cx, cy, 'tsop'))
    for name, colour, a, b, via, note in wires:
        draw_wire(o, name, colour, a, b, via)
    for ref, value, cx, cy, ang in labels:
        if ang == 'to92':
            o.append(text(X(cx + 1.6), Y(cy) - 6, ref, 10, '#111', anchor='start', weight='bold', halo=True))
            o.append(text(X(cx + 1.6), Y(cy) + 6, value, 9, '#333', anchor='start', halo=True))
        elif ang == 'tsop':
            o.append(text(X(cx - 1.9), Y(cy - 0.35), ref, 9.5, '#111', anchor='end', weight='bold', halo=True))
            o.append(text(X(cx - 1.9), Y(cy - 0.35) + 12, value, 9, '#333', anchor='end', halo=True))
        elif ang is None:
            dy = -1.55 if cy < 9 else 1.85
            if ref in ('C2',):
                dy = 0.5
                o.append(text(X(cx - 2.0), Y(cy + dy) + 3, '%s %s' % (ref, value), 9.5, '#111', anchor='end', weight='bold', halo=True))
                continue
            if ref == 'C1':
                o.append(text(X(cx + 1.2), Y(cy) + 4, '%s %s' % (ref, value), 9.5, '#111', anchor='start', weight='bold', halo=True))
                continue
            o.append(text(X(cx), Y(cy + dy) + 4, '%s %s' % (ref, value), 9.5, '#111', weight='bold', halo=True))
        else:
            vertical = abs(abs(ang) - 90) < 30
            if vertical:
                o.append(text(X(cx + 0.95), Y(cy) + 4, '%s %s' % (ref, value), 9.5, '#111', anchor='start', weight='bold', halo=True))
            else:
                o.append(text(X(cx), Y(cy - 0.95), '%s %s' % (ref, value), 9.5, '#111', weight='bold', halo=True))
    # wire tags on long signal runs
    o.append(text(X(18.0), Y(8.5) - 7, 'GPIO34 → U1 OUT', 9, COLOURS['gpio34'], weight='bold', halo=True))
    o.append(text(X(18.0), Y(14.55) - 6, 'GPIO4 → R1 (base)', 9, COLOURS['gpio4'], weight='bold', halo=True))
    # legend + notes
    ly = H_BOARD + 18
    x = MX + BB_X0 * P
    for key, lab in LEGEND:
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-linecap="round"/>'
                 % (x, ly, x + 26, ly, COLOURS[key], 0.42 * P))
        o.append(text(x + 34, ly + 4, lab, 11, '#333', anchor='start'))
        x += 34 + 8 * len(lab) + 26
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#555" stroke-width="%.1f" stroke-linecap="round"/>'
             % (x, ly, x + 26, ly, 0.16 * P))
    o.append(text(x + 34, ly + 4, 'thin = rail bridge (only if the rails are split in the middle)', 11, '#333', anchor='start'))
    for k, n in enumerate(notes):
        o.append(text(MX + BB_X0 * P, ly + 30 + 15 * k, n, 11, '#444', anchor='start'))
    o.append('</svg>')
    return '\n'.join(o) + '\n'


# ------------------------------------------------------------------------------------------- steps
WIRE_COLOUR_NAME = {'5v': 'red', '3v3': 'orange', 'gnd': 'black', 'gpio4': 'blue', 'gpio34': 'green',
                    'bridge5': 'red', 'bridge3': 'orange', 'bridgeg': 'black'}


def value_text(kind, value, extra):
    if kind == 'res':
        v = value[:-1] + ' Ω' if value.endswith('R') else value[:-1] + ' kΩ'
        return v + (' 1 W' if extra.get('w', 0) >= 1 else '')
    return value.replace('uF', ' µF')


def steps_md(legs, wires):
    wmap = {w[0]: w for w in wires}
    out = ['# Breadboard build: hole by hole', '',
           'Generated by `gen_breadboard.py`; the picture is `%s.png`. The connectivity was checked' % os.path.basename(OUT),
           'against the intended netlist, with each 5-hole strip, both rails and every jumper modelled.', '',
           'Rows are numbered 1-63 along the board and columns are a-e | channel | f-j. Each side has an outer **+**',
           'rail and an inner **-** rail, as drawn. If your board marks them the other way round, follow its red/blue',
           'markings.', '',
           '**Check first:** the DOIT DevKit V1’s two pin rows must be **0.9" (22.86 mm)** apart. Then, with its pins',
           'in columns **b** and **i**, it leaves column **a** and column **j** free. A board with rows 1.0" apart',
           'covers one side completely: use two breadboards side by side, or jumper leads.', '',
           '| Step | Item | Holes | Notes |', '|---:|---|---|---|',
           '| 1 | DOIT ESP32 DevKit V1 | b1-b15, i1-i15 | USB toward row 1, off the end of the board. b1 = 3V3, b2 = GND, '
           'b5 = D4, i1 = VIN, i2 = GND, i12 = D34 |']
    n = 2
    order = [('W1', ''), ('W2', ''), ('W3', ''), ('W4', ''), ('B1', ''), ('B2', ''), ('B3', ''), ('B4', ''),
             ('Q1', 'flat face toward the channel'), ('R1', 'base resistor, across the channel'),
             ('R2', 'LED string 1'), ('R3', 'LED string 2'),
             ('D1', 'long leg (anode, +) in %s'), ('D2', 'long leg (anode, +) in %s'),
             ('D3', 'long leg (anode, +) in %s'), ('D4', 'long leg (anode, +) in %s'),
             ('C2', 'bulk for the LED pulses: + leg in the + rail, striped (-) leg in the - rail'),
             ('W6', ''), ('W7', ''), ('W8', ''), ('W5', ''),
             ('U1', 'dome (lens) facing the channel'), ('C1', 'supply filter, striped (-) leg in %s'),
             ('R4', 'supply filter, from the + rail (3V3)'), ('R5', 'OUT pull-up, from the + rail (3V3)'),
             ('W9', ''), ('W10', '')]
    for ref, note in order:
        if ref in wmap:
            _, colour, a, b, via, wnote = wmap[ref]
            out.append('| %d | wire %s, %s | %s → %s | %s |' % (n, ref, WIRE_COLOUR_NAME[colour], hole_name(a),
                                                                     hole_name(b), wnote))
        else:
            kind, value, pins, extra = PARTS[ref]
            holes = ' · '.join('%s %s' % (p, hole_name(legs['%s.%s' % (ref, p)])) for p in pins)
            if '%s' in note:
                note = note % hole_name(legs['%s.%s' % (ref, 'A' if kind == 'led' else '-')])
            out.append('| %d | %s %s | %s | %s |' % (n, ref, value_text(kind, value, extra), holes, note))
        n += 1
    out += ['', 'Firmware defaults match: IR TX = GPIO4, IR RX = GPIO34, status LED = GPIO2 (the DOIT board’s blue',
            'LED), BOOT = GPIO0 (the board’s BOOT button).', '',
            'Current: VIN carries the USB 5 V. Some DOIT clones have a diode in that path, giving about 4.7 V. With the',
            '%s’s V_CE(sat) of about 0.2 V, each string draws (V_IN - 2 x 1.45 V - 0.2 V) / 15 Ω, roughly'
            % PARTS['Q1'][1].split('-')[0],
            '105-125 mA at the carrier peaks.', '']
    if PARTS['Q1'][1] == 'PN2222A':
        out[-1:-1] = ['**Transistor pinout:** this layout assumes a plastic TO-92 PN2222A, whose legs are **E-B-C**',
                      '(flat face toward you, left to right). That is the reverse of the BC337-40 (C-B-E), so the',
                      'collector and emitter holes are swapped compared with `devboard-breadboard.md`. Pinouts vary',
                      'by maker and the metal-can 2N2222 (TO-18) differs again: check your datasheet, and if your part',
                      'is C-B-E, use the BC337 layout instead.', '']
    return '\n'.join(out)


def use_2n2222():
    """PN2222A in a TO-92 is E-B-C (BC337 is C-B-E): the collector and emitter holes swap, so the
    resistor strings move to the collector row (32) and the emitter jumper to row 30."""
    global OUT
    OUT = os.path.join(HERE, 'devboard-breadboard-2n2222')
    PARTS['Q1'] = ('to92', 'PN2222A', {'E': ('j', 30), 'B': ('j', 31), 'C': ('j', 32)}, {'flat': 'down'})
    PARTS['R2'] = ('res', '15R', {'1': ('f', 32), '2': ('f', 25)}, {'w': 1})
    PARTS['R3'] = ('res', '15R', {'1': ('h', 32), '2': ('h', 35)}, {'w': 1})
    for i, w in enumerate(WIRES):
        if w[0] == 'W8':
            WIRES[i] = ('W8', 'gnd', ('i', 30), ('top-', 30), [], 'Q1 emitter to GND')


def main():
    if '--2n2222' in sys.argv:
        use_2n2222()
    legs, wires, errors = build()
    if errors:
        for e in errors:
            print('ERROR', e)
        sys.exit(1)
    nets = len(NETS)
    print('PASS: %d parts, %d wires, %d nets as intended, unused dev-board pins untouched, no covered holes'
          % (len(PARTS), len(wires), nets))
    with open(OUT + '.svg', 'w', encoding='utf-8', newline='\n') as f:
        f.write(svg(legs, wires))
    with open(OUT + '.md', 'w', encoding='utf-8', newline='\n') as f:
        f.write(steps_md(legs, wires))
    try:
        import fitz
    except ImportError:
        print('PyMuPDF not installed: PNG skipped')
    else:
        doc = fitz.open(OUT + '.svg')
        doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(OUT + '.png')
    print('wrote', ', '.join(os.path.basename(OUT) + e for e in ('.svg', '.md', '.png')))


if __name__ == '__main__':
    main()
