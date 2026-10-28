# Veroboard / stripboard layout tool

`stripboard.py` takes a JSON description of a hand-placed stripboard layout and:

- expands footprints (axial, radial, header, DIP, dev-board module, tactile switch) into pins
- checks connectivity per net: shorts, split nets, NC pins touching anything, and optionally the board against a KiCad netlist
- adds the track cuts the layout needs (`--auto-cuts`), as drilled-hole cuts or knife cuts between holes
- warns about physical problems: overlapping bodies, covered holes, bare links over leads, link joints next to cuts, parts hanging off the board
- draws the component side and the mirrored copper side (SVG, plus PNG when PyMuPDF is installed)
- writes a JSON report and a Markdown build guide with a BOM, ordered build steps and a multimeter checklist

It does not place parts or route links for you. Standard library only (Python 3.10+). `pip install pymupdf` adds PNG output.

## Run

```sh
python stripboard.py example.json --auto-cuts --out-dir build/            # everything
python stripboard.py example.json --auto-cuts --netlist example.net.xml --out-dir build/
python stripboard.py example.json --auto-cuts --side component --output component.svg --report report.json
```

| Option | Meaning |
|---|---|
| `--out-dir DIR` | writes `<name>-component.svg/.png`, `<name>-copper.svg/.png`, `<name>-report.json`, `<name>-build.md`. `<name>` comes from `board.name`, or the input file name if there is none. |
| `--output F`, `--side copper\|component` | a single SVG of one side. With no `--out-dir`, the default is `<input>.svg`. |
| `--report F` | the JSON report |
| `--auto-cuts` | cut between neighbouring anchors (pins and link ends) of different nets on a strip, and isolate NC pins |
| `--cut-style hole\|between\|prefer-hole` | auto-cut kind. The default `prefer-hole` drills a free hole if there is one and knife-cuts between holes otherwise. |
| `--netlist F` | KiCad XML netlist to verify against (`kicad-cli sch export netlist --format kicadxml`) |
| `--netlist-ignore R1,BT1` | refs left out of the netlist check (off-board parts) |

Exit codes: 0 valid, 1 electrical error (outputs are still written), 2 invalid input. The outputs always show errors and warnings; nothing is hidden.

## Coordinates

Strips run along rows. Input holes are zero-based `[column,row]` seen from the **component side**. Drawings, the guide and the report also use Veroboard names: rows are lettered A, B, ... (AA after Z) and columns are numbered from 1, so `[0,0]` is **A1** and `[7,1]` is **B8**. On the copper side, left and right swap: column 1 is on the right, and the copper drawing is mirrored to match.

## Input reference

```jsonc
{
  "board": {"columns": 14, "rows": 8, "name": "Button and LED"},
  "components": [ /* see below */ ],
  "links": [{"from": [10,3], "to": [10,0], "net": "GND", "color": "black", "insulated": true}],
  "cuts":  [[4,3], {"between": [4,2]}]
}
```

- **Cuts.** `[x,y]` drills out hole x,y. `{"between":[x,y]}` severs the track between columns x and x+1 on row y. A hole cut cannot be on a hole that holds a lead.
- **Links** are wires on the component side. `net` is optional: when it is missing, it is inferred if one end's strip segment (before auto-cuts) holds pins of exactly one net. When auto-cuts needs a net that can't be inferred, the tool stops and asks for `"net"`. `insulated` defaults to true. `color` is any SVG colour; the default comes from the net (GND black, supplies red, others from a palette).
- **One lead per hole:** a link end cannot share a hole with a pin or another link.

### Components

Common fields: `ref` (unique), `type` (e.g. `resistor`, `diode`, `led`, `ic`), and optional `value`, `part`, `description` (used in the BOM), plus `color` for LEDs.

**Explicit pins** (as before): `"pins": {"1": {"at": [4,1], "net": "VCC"}, "2": {"at": [4,2], "net": "X"}}`. A pin may also have `"number"` for netlist matching.

**Footprints:** `"footprint": ..., "at": [x,y], "rotation": 0|90|180|270`, the parameters below, and `"nets": {pin: net}`. Keys of `nets` can be pin names, pin numbers or module aliases (`L3`, `R1`).

**No connection.** A pin whose net is missing, `null` or `"NC"` is NC. It must not touch any other pin or net: otherwise it is reported in `nc_conflicts` and the board is invalid. Auto-cuts isolates NC pins.

| Footprint | Parameters | Pins at rotation 0 (from `at`) |
|---|---|---|
| `axial` | `span` (lead spacing in holes, default 4; 4 = 1/4 W resistor flat, 3 = DO-34) | `1` at +0, `2` at +span. With `type` diode/led/zener/schottky: `A` at +0, `K` at +span. |
| `radial` | `pitch` (default 1), `diameter` in holes (default 2 = 5 mm LED) | `1`,`2`; for `type` led or diode: `A`, `K` (the flat is on the K side) |
| `header` | `pins` (count), optional `pin_names`, `female` (drawing only) | 1..N along the row; keys are `pin_names` if given. Pin 1 is drawn square. |
| `dip` | `pins` (even), `row_spacing` (default 3 = 0.3"), optional `pin_names` | 1..N/2 along the row, then N/2+1..N back along the second row (counter-clockwise from above, notch at the pin-1 end) |
| `module` | `row_spacing` (e.g. 9 = 0.9"), `left`/`right` pin-name lists from the origin end (`null` = no pin), optional `body` `{extend_start, extend_end, extend_left, extend_right}` in holes, `label`, `numbering` | left row from `at`; right row parallel, `row_spacing` away |
| `tactile` | none | `1` +0, `3` +2 along; `2`, `4` 3 holes across on the second-row side (like a DIP: above at rotation 0, to the right at 90). 1-2 and 3-4 are joined inside. |

**Rotation** turns the footprint clockwise as seen in the component-side view. The direction pins advance (header 1→N, DIP pin 1→N/2, module rows, axial pin 1→2) is:

| rotation | pins advance | second row (DIP / module right row) |
|---|---|---|
| 0 | +column (right, **along** the strip) | 90° anticlockwise of the advance: above, −row |
| 90 | +row (down, **across** the strips) | to the right, +column |
| 180 | −column (left) | below, +row |
| 270 | −row (up) | to the left, −column |

**DIPs, modules and headers go across the strips** (`rotation` 90 or 270) so that each pin has its own strip. The strips must then be cut between the two pin rows; `--auto-cuts` does this. At rotation 90, pin 1 is at `at` and the part extends right and down. A DIP at rotation 90 has pin 1 top-left, pins going down the left column and back up the right one.

**Module pin keys.** Pins are keyed by name. A repeated name gets `#2`, `#3`, ... in order: the left list top to bottom, then the right list. So two GNDs become `GND` and `GND#2`. Every module pin also has the positional aliases `L<n>` and `R<n>` (1-based, counted from the origin end) for use in `nets`. Pin numbers for the netlist come from `numbering`: `sequential` (default: left 1..n, right n+1..), `ccw` (DIP style), or `odd_even` (left odd, right even).

**Tactile switch approximation.** A 6x6 mm switch has legs 6.5 x 4.5 mm apart. On the 2.54 mm grid this becomes 3 holes (7.6 mm, across the strips) x 2 holes (5.1 mm, along a strip), so the legs need slight bending. The pairs 3 holes apart (1-2, 3-4) are joined inside the switch. At rotation 0, the switched pairs share a strip and need a cut between them (auto-cuts adds it). At rotation 90, each joined pair lies on one strip and no cut is needed. Check your switch with a meter.

**Bridges.** `"bridges": [["1","2"], ...]` declares pins that are joined inside a part. They are unioned for connectivity and listed in the report. An unnamed pin in a bridge group takes the group's net. Do not use bridges for resistors, LEDs or IC internals.

**Netlist pin matching.** A schematic node `ref` + `pin` is matched to a layout pin in this order: the part's `netlist_pins` map (`{"schematic pin": ["layout pin", ...]}`), then the pin number, then the pin key, then `pinfunction` against the pin name (ignoring `#n`). Axial/radial A/K pins are numbered as in KiCad (K = 1, A = 2). The tactile default `{"1":["1","2"],"2":["3","4"]}` matches KiCad's 2-pin `SW_Push`.

## Report

`valid`, `shorts`, `disconnected`, `nc_conflicts`, `netlist_mismatches` (all errors), `warnings`, `cuts` (input format, reusable), `cut_list` (with Veroboard names and what each cut separates), `link_list` (with inferred nets), `pins`, `nets`, `bridges`, `segments` (each copper segment and its net) and `continuity_checks`.

## Before you build

The guide orders the build as cuts, links, low parts, sockets/headers, then taller parts. Follow its multimeter checklist before applying power. Check datasheet pinouts, polarity and real part sizes. A passing check is not a safety certification.
