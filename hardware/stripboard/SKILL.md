# Stripboard design skill

1. Describe the board using JSON (see `example.json`). Use zero-based component-side hole coordinates.
2. Place components with `ref`, optional `type`, and pin coordinates with the intended net; use insulated `links` where needed.
3. Run `stripboard.py <input.json> --auto-cuts --side component --output component.svg`.
4. Run again with `--side copper --output copper.svg --report report.json`.
5. Check `report.valid`, `shorts`, `disconnected`, and `cuts`; amend component placement / jumpers if invalid. Never conceal reported errors.
6. Show both SVGs and list copper cut coordinates in a build guide. The copper-side view is horizontally mirrored relative to the component-side view.
7. Verify physical placement, pinouts and continuity before power.

This is a renderer/connectivity validator, not an autorouter. Internal component behaviour is not modelled; do not model resistors, LEDs or IC pins as wire links.
