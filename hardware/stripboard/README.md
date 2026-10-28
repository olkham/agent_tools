# Veroboard / stripboard layout generator

Python 3 standard-library tool for drawing **component-side** and **copper-side** SVG layouts and checking electrical connectivity. The tool displays physical component pin positions, reference labels, jumpers, and clearly marked copper-track cuts. The two views are horizontally mirrored, as they would be when physically flipping a board.

## Run

```sh
python hardware/stripboard/stripboard.py hardware/stripboard/example.json --auto-cuts --side component --output component.svg
python hardware/stripboard/stripboard.py hardware/stripboard/example.json --auto-cuts --side copper --output copper.svg --report report.json
```

The provided example produces a valid layout with an automatic track cut at **[7,1]**, two jumper links, and components R1, D1, J1, J2 and TP1. The cut should be made **on the copper side**, at the coordinates referenced from the component side. Confirm orientation before cutting.

## Input format

`board`: `{"columns":12,"rows":6}`. Coordinates are zero-based `[column,row]`, referenced from the component side; strips run along rows. `components`: array of `{ref,type?,pins:{pin:{at:[x,y],net:"name"}}}`. `cuts`: array of copper cuts `[x,y]`. `links`: array of insulated jumpers `{"from":[x,y],"to":[x,y]}`.

`--auto-cuts` cuts unused holes between adjacent terminals belonging to different named nets on the same strip. It **does not place components, route jumpers, or guarantee a functional schematic**. Components do not themselves provide an electrical connection between pins. Cut positions cannot coincide with component pins. Reports flag shorted and disconnected declared nets. Return codes: 0 valid, 1 electrical error, 2 invalid input.

## Assembly checks

On the **copper side**, red crossed circles indicate where copper must be removed and blue lines denote insulated jumper wires; component pins are yellow. On the component side, the rendering includes approximate component bodies and pin labels, not precise mechanical footprints. Verify datasheet pinouts, polarity, actual component dimensions, jumper clearance, cut orientation, and continuity with a multimeter before power-up. A validation result is not a safety certification.
