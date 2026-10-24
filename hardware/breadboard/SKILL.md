---
name: breadboard-layout
description: Use when asked to plan, draw or document a breadboard build of a circuit (parts, jumpers, hole-by-hole steps) with verified connectivity.
---

# Breadboard layout generator

1. Copy `gen_breadboard.py` into the target project; output goes next to it (change `OUT` for the file name).
2. Get the intended netlist (from the schematic/BOM). Write it into `NETS` as `REF.PIN` lists; add board-internal ties to `INTERNAL`.
3. Set the dev-board pin order in `DEV_B` / `DEV_I` (columns b and i, row 1 = USB end).
4. Place parts in `PARTS` as `ref: (kind, value, {pin: hole}, extra)`. Hole = `('a'..'j', row)` or `(rail, near_row)` with rail in `top+ top- bot- bot+`. Kinds: `res` (`w` watts), `led` (`A`,`K`), `ecap` (`+`,`-`, `d` mm), `to92` (`C`,`B`,`E`), `tsop` (`VS`,`GND`,`OUT`).
5. Add jumpers in `WIRES`: `(name, colour_key, from, to, waypoints, note)`; add new colour keys to `COLOURS` and `WIRE_COLOUR_NAME`. Add `B*` bridges across row 31 on any rail you use on both halves.
6. Run `python3 gen_breadboard.py`. Fix every `ERROR` line (split net, unintended merge, occupied/covered hole) by moving parts or wires, and rerun until `PASS`.
7. Update the step `order` in `steps_md()` and the text in `svg()` (title, notes, wire tags) and `steps_md()` (firmware/current notes) for the new circuit.
8. Open the PNG to check that labels and wires are readable, then hand over the `.png` and `.md`.

Rules: never edit the outputs by hand, always regenerate. Only trust the layout once the script prints `PASS`.
