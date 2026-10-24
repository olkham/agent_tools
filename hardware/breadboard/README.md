# gen_breadboard.py

Turns a hand-placed breadboard plan into a verified wiring picture and build guide.

**Outputs** (next to the script):
- `devboard-breadboard.svg` – top view of an 830-point breadboard with every part and jumper
- `devboard-breadboard.png` – rasterised copy (only if PyMuPDF is installed)
- `devboard-breadboard.md` – step-by-step build table, hole by hole

**Checks before drawing** (exits 1 on any failure):
- every lead/wire sits in a real, free hole
- the connectivity the breadboard creates (5-hole strips, rails, jumpers) matches `NETS` exactly: no missing links, no shorts, unused pins left alone
- rails are treated as split mid-board (worst case), so the plan works on either rail type
- upright parts (LEDs, caps, TO-92, IR receiver) don't cover holes or collide

## Usage

```
python3 gen_breadboard.py            # default build
python3 gen_breadboard.py --2n2222   # variant with an E-B-C transistor
pip install pymupdf                  # optional, for PNG output
```

Stdlib only otherwise.

## Adapting

The example is an ESP32 DevKit V1 IR blaster. Edit the data near the top: `DEV_B`/`DEV_I` (dev-board pins), `PARTS`, `WIRES`, `NETS`, `INTERNAL`. Supported part kinds: `devkit`, `res`, `led`, `ecap`, `to92`, `tsop`. See [SKILL.md](SKILL.md).
