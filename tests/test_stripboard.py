import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "hardware/stripboard/stripboard.py"
spec = importlib.util.spec_from_file_location("stripboard", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def board(pins, cuts=None, links=None):
    return {"board": {"columns": 10, "rows": 3},
            "components": [{"ref": f"P{i}", "pins": {"1": {"at": [x,y], "net": net}}}
                           for i, (x,y,net) in enumerate(pins)],
            "cuts": cuts or [], "links": links or []}

class StripboardTests(unittest.TestCase):
    def test_connected_row(self):
        svg, report = module.generate(board([(1,0,"A"), (8,0,"A")]))
        self.assertTrue(report["valid"])
        self.assertIn("<svg", svg)

    def test_short_detection(self):
        _, r = module.generate(board([(1,0,"A"), (8,0,"B")]))
        self.assertEqual(r["shorts"], [["A","B"]])

    def test_auto_cut(self):
        _, r = module.generate(board([(1,0,"A"), (8,0,"B")]), auto_cuts=True)
        self.assertTrue(r["valid"])
        self.assertEqual(len(r["cuts"]), 1)

    def test_disconnected(self):
        _, r = module.generate(board([(1,0,"A"), (8,1,"A")]))
        self.assertEqual(r["disconnected"], {"A": 2})

    def test_jumper(self):
        _, r = module.generate(board([(1,0,"A"), (8,1,"A")], links=[{"from":[1,0],"to":[8,1]}]))
        self.assertTrue(r["valid"])

    def test_cut_on_pin_rejected(self):
        with self.assertRaises(ValueError):
            module.generate(board([(1,0,"A")], cuts=[[1,0]]))

    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            module.generate(board([(1,0,"A"), (1,0,"B")]))

    def test_auto_cut_adjacent_pin_fails(self):
        with self.assertRaises(ValueError):
            module.generate(board([(1,0,"A"), (2,0,"B")]), auto_cuts=True)

    def test_mirrored_component_view(self):
        data = board([(1,0,"A")])
        copper, r1 = module.generate(data, side="copper")
        component, r2 = module.generate(data, side="component")
        self.assertEqual(r1, r2)
        self.assertIn('cx="304"', copper)
        self.assertIn('cx="80"', component)

if __name__ == "__main__":
    unittest.main()
