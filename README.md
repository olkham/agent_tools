# agent_tools

Small, self-contained tools written with (and for) coding agents. Each tool lives in its own folder with:

- the script(s)
- `README.md`: what it does and how to run it
- `SKILL.md`: instructions an agent can follow to adapt and use it

## Tools

| Tool | What it does |
|---|---|
| [hardware/breadboard](hardware/breadboard/) | Generates a checked breadboard layout (SVG/PNG) and hole-by-hole build steps from a parts + netlist description. |
| [hardware/stripboard](hardware/stripboard/) | Checks a Veroboard layout from footprints, nets and links (optionally against a KiCad netlist), adds track cuts, and draws the component and mirrored copper sides with a build guide and multimeter checklist. |
