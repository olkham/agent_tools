---
name: stripboard-layout
description: Use when asked to lay out, check, draw or document a stripboard / Veroboard build (parts, track cuts, links, build guide) with verified connectivity.
---

# Stripboard design skill

1. Get the circuit's netlist (ideally a KiCad XML netlist: `kicad-cli sch export netlist --format kicadxml`) and the real part sizes.
2. Write the layout JSON (see `example.json` and the README reference). Coordinates are zero-based `[column,row]` from the component side, and strips run along rows. Use footprints with `at`, `rotation` and `nets` rather than hand-entering pins.
   - Put DIPs, modules and multi-pin headers **across** the strips (`rotation` 90 or 270), so each pin has its own strip.
   - Leave out or `"NC"` the unused pins. They must end up isolated.
   - Give links a `"net"` when the tool can't infer it, and links never share a hole with anything.
3. Run `python stripboard.py layout.json --auto-cuts --out-dir out/ [--netlist board.xml --netlist-ignore BT1]`.
4. Read the printed summary. Fix every error (`shorts`, `disconnected`, `nc_conflicts`, `netlist_mismatches`) by moving parts, adding links or adding cuts, and rerun until `valid` is true (exit code 0). Review each warning and fix it or justify it. Never hide or edit out reported problems.
5. Open both PNGs/SVGs and check that the labels are readable and the parts physically fit. Hand over `out/<name>-build.md` with the pictures. The copper view is mirrored: column 1 is on the right.
6. Before power, the builder does the guide's multimeter checklist.

This is a checker, renderer and guide writer, not an autorouter. Do not model resistor, LED or IC internals as connections. Use `bridges` only for pins that are really joined inside a part (e.g. tactile switch legs).
