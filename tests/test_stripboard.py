import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "hardware/stripboard"
SCRIPT = ROOT / "stripboard.py"
spec = importlib.util.spec_from_file_location("stripboard", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

EXAMPLE = json.loads((ROOT / "example.json").read_text(encoding="utf-8"))
NETLIST = (ROOT / "example.net.xml").read_text(encoding="utf-8")


def board(pins, cuts=None, links=None, w=10, h=3):
    return {"board": {"columns": w, "rows": h},
            "components": [{"ref": f"P{i}", "pins": {"1": {"at": [x, y], "net": net}}}
                           for i, (x, y, net) in enumerate(pins)],
            "cuts": cuts or [], "links": links or []}


def run(data, **kw):
    return module.generate(data, **kw)[1]


def one(comp, w=20, h=20, **kw):
    return run({"board": {"columns": w, "rows": h}, "components": [comp]}, **kw)


def pin_at(report, label):
    return tuple(report["pins"][label]["at"])


class BasicTests(unittest.TestCase):
    def test_connected_row(self):
        svg, report = module.generate(board([(1, 0, "A"), (8, 0, "A")]))
        self.assertTrue(report["valid"])
        self.assertIn("<svg", svg)

    def test_short_detection(self):
        self.assertEqual(run(board([(1, 0, "A"), (8, 0, "B")]))["shorts"], [["A", "B"]])

    def test_auto_cut(self):
        r = run(board([(1, 0, "A"), (8, 0, "B")]), auto_cuts=True)
        self.assertTrue(r["valid"])
        self.assertEqual(len(r["cuts"]), 1)

    def test_disconnected(self):
        self.assertEqual(run(board([(1, 0, "A"), (8, 1, "A")]))["disconnected"], {"A": 2})

    def test_jumper(self):
        r = run(board([(1, 0, "A"), (8, 1, "A")], links=[{"from": [2, 0], "to": [7, 1]}]))
        self.assertTrue(r["valid"])

    def test_cut_on_pin_rejected(self):
        with self.assertRaises(ValueError):
            run(board([(1, 0, "A")], cuts=[[1, 0]]))

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            run(board([(1, 0, "A"), (1, 0, "B")]))

    def test_auto_cut_adjacent_pin_fails_with_hole_style(self):
        with self.assertRaises(ValueError):
            run(board([(1, 0, "A"), (2, 0, "B")]), auto_cuts=True, cut_style="hole")

    def test_mirrored_component_view(self):
        data = board([(1, 0, "A")])
        copper, r1 = module.generate(data, side="copper")
        component, r2 = module.generate(data, side="component")
        self.assertEqual(r1, r2)
        self.assertIn('cx="304"', copper)
        self.assertIn('cx="80"', component)

    def test_veroboard_names(self):
        self.assertEqual([module.row_name(i) for i in (0, 1, 25, 26, 27, 51, 52)], ["A", "B", "Z", "AA", "AB", "AZ", "BA"])
        self.assertEqual(module.hole_name((7, 1)), "B8")
        r = run(board([(1, 0, "A"), (8, 0, "B")]), auto_cuts=True)
        self.assertEqual(r["cut_list"][0]["name"], module.hole_name(tuple(r["cuts"][0])))
        self.assertEqual(r["pins"]["P0.1"]["hole"], "A2")


class FootprintTests(unittest.TestCase):
    def test_header_rotation(self):
        expect = {0: [(5, 5), (6, 5), (7, 5)], 90: [(5, 5), (5, 6), (5, 7)],
                  180: [(5, 5), (4, 5), (3, 5)], 270: [(5, 5), (5, 4), (5, 3)]}
        for rot, holes in expect.items():
            r = one({"ref": "J1", "footprint": "header", "at": [5, 5], "rotation": rot, "pins": 3})
            self.assertEqual([pin_at(r, f"J1.{i}") for i in (1, 2, 3)], holes, rot)

    def test_header_pin_names_and_nets(self):
        r = one({"ref": "J1", "footprint": "header", "at": [0, 0], "rotation": 90, "pins": 3,
                 "pin_names": ["GND", "VCC", "SIG"], "nets": {"GND": "GND", "2": "VCC"}})
        self.assertEqual(r["pins"]["J1.VCC"], {"at": [0, 1], "hole": "B1", "net": "VCC", "number": "2"})
        self.assertIsNone(r["pins"]["J1.SIG"]["net"])

    def test_axial_resistor_and_diode(self):
        r = one({"ref": "R1", "type": "resistor", "footprint": "axial", "at": [2, 3], "rotation": 90, "span": 4})
        self.assertEqual((pin_at(r, "R1.1"), pin_at(r, "R1.2")), ((2, 3), (2, 7)))
        svg, r = module.generate({"board": {"columns": 10, "rows": 3}, "components": [
            {"ref": "D1", "type": "diode", "footprint": "axial", "at": [1, 1], "span": 3}]}, side="component")
        self.assertEqual((pin_at(r, "D1.A"), pin_at(r, "D1.K")), ((1, 1), (4, 1)))
        self.assertEqual(r["pins"]["D1.K"]["number"], "1")       # KiCad diode/LED: pin 1 = K
        self.assertIn('class="band"', svg)

    def test_radial_led(self):
        svg, r = module.generate({"board": {"columns": 10, "rows": 5}, "components": [
            {"ref": "D1", "type": "led", "footprint": "radial", "at": [3, 1], "rotation": 90}]}, side="component")
        self.assertEqual((pin_at(r, "D1.A"), pin_at(r, "D1.K")), ((3, 1), (3, 2)))
        self.assertIn('class="led"', svg)

    def test_dip_numbering(self):
        r = one({"ref": "U1", "footprint": "dip", "at": [2, 2], "rotation": 90, "pins": 8})
        got = {n: pin_at(r, f"U1.{n}") for n in range(1, 9)}
        self.assertEqual(got, {1: (2, 2), 2: (2, 3), 3: (2, 4), 4: (2, 5), 5: (5, 5), 6: (5, 4), 7: (5, 3), 8: (5, 2)})
        with self.assertRaises(ValueError):
            one({"ref": "U1", "footprint": "dip", "at": [2, 2], "pins": 7})

    def test_dip_across_strips_auto_cuts_between_rows(self):
        r = one({"ref": "U1", "footprint": "dip", "at": [2, 2], "rotation": 90, "pins": 8,
                 "nets": {"1": "GND", "8": "VCC"}}, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertEqual(sorted(tuple(c) for c in r["cuts"]), [(4, 2), (4, 3), (4, 4), (4, 5)])

    def test_module_duplicate_names(self):
        comp = {"ref": "U1", "footprint": "module", "at": [1, 1], "rotation": 90, "row_spacing": 9,
                "left": ["3V3", "GND", "D15"], "right": ["VIN", "GND", None, "D2"], "label": "ESP32",
                "body": {"extend_end": 4}, "nets": {"3V3": "3V3", "GND": "GND", "GND#2": "GND", "R4": "LED"}}
        r = one(comp, w=14, h=12)
        self.assertEqual(pin_at(r, "U1.GND"), (1, 2))
        self.assertEqual(pin_at(r, "U1.GND#2"), (10, 2))
        self.assertEqual(pin_at(r, "U1.D2"), (10, 4))
        self.assertEqual(r["pins"]["U1.D2"]["net"], "LED")
        self.assertEqual(r["pins"]["U1.VIN"]["number"], "4")        # sequential: left 1..3, right 4..
        self.assertEqual(r["disconnected"], {})                       # both GNDs share strip C
        self.assertEqual([(c["pin"], c["connected_to"]) for c in r["nc_conflicts"]], [("U1.VIN", ["3V3"])])
        self.assertTrue(one(comp, w=14, h=12, auto_cuts=True)["valid"])  # auto-cuts isolates the NC pins
        comp["numbering"] = "ccw"
        self.assertEqual(one(comp, w=14, h=12)["pins"]["U1.VIN"]["number"], "7")
        comp["nets"] = {"NOPE": "X"}
        with self.assertRaises(ValueError):
            one(comp, w=14, h=12)

    def test_module_body_extent_warns_off_board(self):
        r = one({"ref": "U1", "footprint": "module", "at": [1, 1], "rotation": 90, "row_spacing": 3,
                 "left": ["A", "B"], "right": ["C", "D"], "body": {"extend_end": 4}}, w=8, h=4)
        self.assertIn("off_board", [w["kind"] for w in r["warnings"]])

    def test_tactile_bridges(self):
        data = {"board": {"columns": 12, "rows": 8}, "components": [
            {"ref": "SW1", "footprint": "tactile", "at": [2, 4], "nets": {"1": "BTN", "3": "GND"}},
            {"ref": "J1", "pins": {"1": {"at": [0, 1], "net": "BTN"}, "2": {"at": [9, 4], "net": "GND"}}}]}
        r = run(data, auto_cuts=True)
        self.assertEqual([pin_at(r, f"SW1.{i}") for i in "1234"], [(2, 4), (2, 1), (4, 4), (4, 1)])
        self.assertTrue(r["valid"], r)                       # J1.1 reaches SW1.1 only through the 1-2 bridge
        self.assertEqual(r["pins"]["SW1.2"]["net"], "BTN")
        self.assertTrue(r["pins"]["SW1.2"]["net_inherited_from_bridge"])
        self.assertEqual([b["pins"] for b in r["bridges"]], [["1", "2"], ["3", "4"]])
        rot = run({"board": {"columns": 12, "rows": 8}, "components": [
            {"ref": "SW1", "footprint": "tactile", "at": [2, 1], "rotation": 90, "nets": {"1": "BTN", "3": "GND"}}]})
        self.assertEqual([pin_at(rot, f"SW1.{i}") for i in "1234"], [(2, 1), (5, 1), (2, 3), (5, 3)])
        self.assertTrue(rot["valid"])                         # rotated: each joined pair on one strip, no cut

    def test_generic_bridges(self):
        data = {"board": {"columns": 6, "rows": 3}, "components": [
            {"ref": "X1", "pins": {"a": {"at": [0, 0], "net": "N"}, "b": {"at": [0, 2]}}, "bridges": [["a", "b"]]},
            {"ref": "J1", "pins": {"1": {"at": [5, 2], "net": "N"}}}]}
        r = run(data)
        self.assertTrue(r["valid"])
        self.assertEqual(r["bridges"][0]["holes"], ["A1", "C1"])

    def test_bad_footprint_inputs(self):
        for comp in ({"ref": "X", "footprint": "blob", "at": [0, 0]},
                     {"ref": "X", "footprint": "header", "at": [0, 0], "pins": 3, "rotation": 45},
                     {"ref": "X", "footprint": "header", "at": [18, 0], "pins": 3},
                     {"ref": "X", "footprint": "header", "at": [0, 0], "pins": 2, "pin_names": ["A"]}):
            with self.assertRaises(ValueError):
                one(comp)


class LinkAndCutTests(unittest.TestCase):
    def test_link_end_cannot_share_pin_hole(self):
        with self.assertRaises(ValueError):
            run(board([(1, 0, "A"), (8, 1, "A")], links=[{"from": [1, 0], "to": [8, 2]}]))
        with self.assertRaises(ValueError):
            run(board([], links=[{"from": [1, 0], "to": [1, 2]}, {"from": [1, 2], "to": [5, 2]}]))

    def test_auto_cut_avoids_link_holes(self):
        # Row 0: A at 1, link end (net B) at 3, B at 5. The old tool cut hole 3 and then failed.
        data = board([(1, 0, "A"), (5, 0, "B"), (6, 2, "B")], links=[{"from": [3, 0], "to": [3, 2]}])
        r = run(data, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["cuts"], [[2, 0]])
        self.assertEqual(r["link_list"][0]["net"], "B")
        self.assertEqual(r["link_list"][0]["net_source"], "inferred")

    def test_link_net_inferred_and_cut(self):
        # The link brings A from row 1 onto row 0, which holds B: the link end must be cut away from B.
        data = board([(1, 1, "A"), (8, 0, "B"), (2, 0, "A")], links=[{"from": [5, 1], "to": [5, 0]}])
        self.assertEqual(run(data)["shorts"], [["A", "B"]])
        r = run(data, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["cuts"], [[7, 0]])

    def test_link_net_needed(self):
        data = board([(1, 0, "A"), (8, 0, "B"), (1, 2, "A"), (8, 2, "C")], links=[{"from": [4, 0], "to": [4, 2]}])
        with self.assertRaisesRegex(ValueError, '"net"'):
            run(data, auto_cuts=True)
        data["links"][0]["net"] = "A"
        r = run(data, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["link_list"][0]["net_source"], "given")

    def test_between_cut_allows_adjacent_pins(self):
        data = board([(1, 0, "A"), (2, 0, "B")], cuts=[{"between": [1, 0]}])
        r = run(data)
        self.assertTrue(r["valid"])
        self.assertEqual(r["cut_list"][0]["name"], "A2|A3")
        r = run(board([(1, 0, "A"), (2, 0, "B")]), auto_cuts=True)            # default prefer-hole
        self.assertEqual(r["cuts"], [{"between": [1, 0]}])
        self.assertTrue(r["valid"])
        r = run(board([(1, 0, "A"), (5, 0, "B")]), auto_cuts=True, cut_style="between")
        self.assertEqual(r["cuts"], [{"between": [2, 0]}])
        with self.assertRaises(ValueError):
            run(board([(1, 0, "A")], cuts=[{"between": [9, 0]}]))         # no column to the right

    def test_cuts_drawn_distinctly(self):
        data = board([(1, 0, "A"), (2, 0, "B"), (5, 1, "C"), (8, 1, "D")], cuts=[{"between": [1, 0]}, [6, 1]])
        svg, r = module.generate(data, side="copper")
        self.assertTrue(r["valid"])
        self.assertEqual(svg.count('class="cut-between"'), 1)
        self.assertEqual(svg.count('class="cut-hole"'), 1)


class NcTests(unittest.TestCase):
    def test_nc_pin_conflict(self):
        data = {"board": {"columns": 10, "rows": 2}, "components": [
            {"ref": "J1", "pins": {"1": {"at": [1, 0]}, "2": {"at": [1, 1], "net": "NC"}}},
            {"ref": "R1", "pins": {"1": {"at": [6, 0], "net": "A"}, "2": {"at": [6, 1], "net": "B"}}}]}
        r = run(data)
        self.assertFalse(r["valid"])
        self.assertEqual([(c["pin"], c["connected_to"]) for c in r["nc_conflicts"]], [("J1.1", ["A"]), ("J1.2", ["B"])])
        r = run(data, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["nc_conflicts"], [])
        self.assertEqual(len(r["cuts"]), 2)

    def test_two_nc_pins_must_not_touch(self):
        data = board([(1, 0, None), (5, 0, None)])
        self.assertEqual(len(run(data)["nc_conflicts"]), 2)
        self.assertTrue(run(data, auto_cuts=True)["valid"])


class WarningTests(unittest.TestCase):
    def kinds(self, data, **kw):
        return [w["kind"] for w in run(data, **kw)["warnings"]]

    def test_overlap_and_covered(self):
        data = {"board": {"columns": 10, "rows": 8}, "components": [
            {"ref": "R1", "type": "resistor", "footprint": "axial", "at": [1, 1], "span": 4},
            {"ref": "R2", "type": "resistor", "footprint": "axial", "at": [3, 0], "rotation": 90, "span": 4}]}
        self.assertIn("overlap", self.kinds(data))
        data["components"][1]["at"] = [3, 2]
        self.assertEqual(self.kinds(data), [])
        data["components"].append({"ref": "TP1", "pins": {"1": {"at": [2, 1]}}})
        self.assertIn("covered_hole", self.kinds(data))

    def test_bare_link_and_link_by_cut(self):
        data = board([(3, 1, "A"), (1, 0, "B"), (5, 0, "B")], links=[{"from": [1, 1], "to": [6, 1], "insulated": False}])
        kinds = self.kinds(data)
        self.assertIn("bare_link", kinds)
        data["links"][0]["insulated"] = True
        self.assertNotIn("bare_link", self.kinds(data))
        data = board([(1, 0, "A"), (8, 1, "A")], cuts=[[3, 0]], links=[{"from": [2, 0], "to": [2, 1]}])
        self.assertIn("link_by_cut", self.kinds(data))


class NetlistTests(unittest.TestCase):
    def test_example_matches_netlist(self):
        r = run(EXAMPLE, auto_cuts=True, netlist=NETLIST)
        self.assertTrue(r["netlist_checked"])
        self.assertEqual(r["netlist_mismatches"], [])
        self.assertTrue(r["valid"])

    def test_swapped_led_is_reported(self):
        bad = NETLIST.replace('ref="D1" pin="1" pinfunction="K"', 'ref="D1" pin="X" pinfunction="K"') \
                     .replace('ref="D1" pin="2" pinfunction="A"', 'ref="D1" pin="1" pinfunction="K"') \
                     .replace('ref="D1" pin="X" pinfunction="K"', 'ref="D1" pin="2" pinfunction="A"')
        r = run(EXAMPLE, auto_cuts=True, netlist=bad)
        self.assertFalse(r["valid"])
        kinds = {m["kind"] for m in r["netlist_mismatches"]}
        self.assertIn("merged", kinds)
        self.assertIn("split", kinds)

    def test_missing_refs_and_ignore(self):
        extra = NETLIST.replace('<net code="1" name="GND" class="Default">',
                                '<net code="1" name="GND" class="Default"><node ref="BT1" pin="2" pinfunction="-"/>')
        r = run(EXAMPLE, auto_cuts=True, netlist=extra)
        self.assertEqual([(m["kind"], m["ref"]) for m in r["netlist_mismatches"]], [("ref_missing_in_layout", "BT1")])
        self.assertTrue(run(EXAMPLE, auto_cuts=True, netlist=extra, netlist_ignore=["BT1"])["valid"])
        no_tp = NETLIST.replace('<node ref="TP1" pin="1" pinfunction="1" pintype="passive"/>', "") \
                       .replace('<comp ref="TP1"><value>TestPoint</value></comp>', "")
        r = run(EXAMPLE, auto_cuts=True, netlist=no_tp)
        self.assertEqual([m["kind"] for m in r["netlist_mismatches"]], ["ref_missing_in_schematic"])

    def test_pinfunction_fallback(self):
        xml = ('<export><nets><net code="1" name="N1"><node ref="J1" pin="9" pinfunction="SIG"/>'
               '<node ref="J2" pin="1"/></net></nets></export>')
        data = {"board": {"columns": 6, "rows": 1}, "components": [
            {"ref": "J1", "pins": {"SIG": {"at": [0, 0], "net": "S"}}},
            {"ref": "J2", "pins": {"1": {"at": [5, 0], "net": "S"}}}]}
        self.assertEqual(run(data, netlist=xml)["netlist_mismatches"], [])

    def test_bad_xml(self):
        with self.assertRaises(ValueError):
            run(EXAMPLE, netlist="<export><nets>")


class OutputTests(unittest.TestCase):
    def test_example_valid(self):
        r = run(EXAMPLE, auto_cuts=True)
        self.assertTrue(r["valid"], r)
        self.assertIn({"between": [4, 2]}, r["cuts"])
        self.assertIsNone(r["pins"]["J1.SPARE"]["net"])

    def test_out_dir(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                module.main([str(ROOT / "example.json"), "--auto-cuts", "--out-dir", d,
                             "--netlist", str(ROOT / "example.net.xml")])
            names = {p.name for p in pathlib.Path(d).iterdir()}
            for suffix in ("component.svg", "copper.svg", "report.json", "build.md"):
                self.assertIn(f"Button-and-LED-{suffix}", names)
            try:
                import fitz  # noqa: F401
                self.assertIn("Button-and-LED-copper.png", names)
            except ImportError:
                self.assertIn("PNG skipped", out.getvalue())
            guide = (pathlib.Path(d) / "Button-and-LED-build.md").read_text(encoding="utf-8")
            for needle in ("Layout check: PASS", "| Ref | Type / value | Footprint |", "knife-cut between **C5\\|C6**",
                           "column 1 is on the RIGHT", "Must NOT beep", "band (cathode K) at B12", "## Warnings"):
                self.assertIn(needle, guide)
            steps = [line for line in guide.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
            phases = [int(line.split("|")[2].strip()[0]) for line in steps]
            self.assertEqual(phases, sorted(phases))
            report = json.loads((pathlib.Path(d) / "Button-and-LED-report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["valid"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "bad.json"
            bad.write_text(json.dumps(board([(1, 0, "A"), (8, 0, "B")])), encoding="utf-8")
            for args, code in (([], 1), (["--auto-cuts"], 0)):
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
                    module.main([str(bad), "--output", str(pathlib.Path(d) / "x.svg")] + args)
                    raise SystemExit(0)
                self.assertEqual(cm.exception.code, code)
            bad.write_text("{}", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                module.main([str(bad)])
            self.assertEqual(cm.exception.code, 2)

    def test_copper_labels_and_legend(self):
        data = board([(1, 0, "VCC"), (8, 0, "GND")])
        svg, _ = module.generate(data, side="copper", auto_cuts=True)
        self.assertIn('class="netlabel"', svg)
        self.assertIn("strip-unused", svg)
        self.assertIn("between-hole cut (knife)", svg)
        # copper side: column 1 is drawn at the right-hand end
        self.assertIn('<text x="336" y="70" font-size="10" text-anchor="middle" font-weight="normal" fill="#555">1</text>', svg)
        comp, _ = module.generate(data, side="component", auto_cuts=True)
        self.assertIn('<text x="48" y="70" font-size="10" text-anchor="middle" font-weight="normal" fill="#555">1</text>', comp)


if __name__ == "__main__":
    unittest.main()
