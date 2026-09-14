import copy
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_chain", ROOT/"scripts"/"render_chain.py")
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


class RenderChainTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT/"assets"/"产业链图模板.json").read_text(encoding="utf-8"))

    def test_template_and_semantic_counts(self):
        RENDER.validate(self.data)
        svg = ET.fromstring(RENDER.render_svg(self.data))
        node_groups = [e for e in svg.iter() if "data-node-id" in e.attrib]
        edges = [e for e in svg.iter() if "data-source" in e.attrib]
        self.assertEqual(svg.attrib["data-node-count"], str(len(self.data["nodes"])))
        self.assertEqual(svg.attrib["data-edge-count"], str(len(self.data["edges"])))
        self.assertEqual(len(node_groups), len(self.data["nodes"]))
        self.assertEqual(len(edges), len(self.data["edges"]))
        self.assertEqual([(e.attrib["data-source"], e.attrib["data-target"]) for e in edges],
                         [(e["source"], e["target"]) for e in self.data["edges"]])
        mmd = RENDER.render_mermaid(self.data)
        self.assertEqual(mmd.count(":::") , len(self.data["nodes"]))
        self.assertEqual(sum(" -->|" in line or " -.->|" in line for line in mmd.splitlines()), len(self.data["edges"]))
        names = {n["id"]: RENDER.mermaid_id(n["id"]) for n in self.data["nodes"]}
        for edge in self.data["edges"]:
            arrow = "-->" if edge.get("type", "main") == "main" else "-.->"
            self.assertIn(f'{names[edge["source"]]} {arrow}|"{RENDER.mermaid_text(edge["label"])}"| {names[edge["target"]]}', mmd)

    def test_chinese_special_characters(self):
        text = '中文<&"[]{}|`#\\'
        self.data["nodes"][0]["title"] = text
        self.data["nodes"][0]["lines"] = []
        self.data["edges"][0]["label"] = text
        svg = RENDER.render_svg(self.data)
        root = ET.fromstring(svg)
        self.assertIn(text, [e.text for e in root.iter()])
        mmd = RENDER.render_mermaid(self.data)
        self.assertIn("#91;", mmd)
        self.assertIn("#34;", mmd)
        self.assertNotIn(text, RENDER.render_html(self.data, svg, mmd))

    def test_bad_geometry_and_nodes(self):
        mutations = [
            lambda d: d["nodes"].append(copy.deepcopy(d["nodes"][0])),
            lambda d: d["edges"][0].update(target="missing"),
            lambda d: d["edges"][0].update(points=[[500,220],[665,330]]),
            lambda d: d["nodes"][1].update(x=400),
            lambda d: d["nodes"][0].update(x=float("nan")),
            lambda d: d["edges"][0].update(points=[[495,225],[665,300],[665,330]]),
            lambda d: d["edges"][0].update(points=[[495,225],[495,350],[665,350],[665,330]]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.data)
                mutation(data)
                with self.assertRaises(ValueError):
                    RENDER.validate(data)

    def test_long_text_rejected(self):
        self.data["nodes"][0]["title"] = "非常长的角色标题"*20
        with self.assertRaises(ValueError):
            RENDER.render_svg(self.data)

    def test_mermaid_theme_and_direction(self):
        mmd = RENDER.render_mermaid(self.data)
        self.assertTrue(mmd.startswith("---\nconfig:\n  theme: base\n"))
        self.assertIn("curve: stepAfter", mmd)
        self.assertIn("Arial, sans-serif", mmd)
        self.assertIn("background: '#f5f9fc'", mmd)
        self.assertIn("flowchart TB", mmd)
        self.data["direction"] = "LR"
        RENDER.validate(self.data)
        self.assertIn("flowchart LR", RENDER.render_mermaid(self.data))
        self.data["direction"] = "arbitrary"
        with self.assertRaises(ValueError):
            RENDER.validate(self.data)

    def test_self_loop_valid_and_invalid(self):
        edge = {"source": "software", "target": "software", "label": "迭代",
                "type": "main", "points": [[330,170],[295,170],[295,100],[400,100],[400,115]],
                "label_x": 345, "label_y": 95}
        self.data["edges"].append(edge)
        RENDER.validate(self.data)
        self.assertIn('n_software -->|"迭代"| n_software', RENDER.render_mermaid(self.data))
        ET.fromstring(RENDER.render_svg(self.data))
        valid = copy.deepcopy(edge)
        edge["points"] = [[330,170],[295,170],[295,100],[330,100],[330,170]]
        with self.assertRaisesRegex(ValueError, "distinct exit and entry"):
            RENDER.validate(self.data)
        edge.update(valid)
        edge["points"] = [[330,170],[400,170],[400,115]]
        with self.assertRaisesRegex(ValueError, "crosses node"):
            RENDER.validate(self.data)

    def test_label_box_not_outside_or_over_node(self):
        for changes, message in [({"label_x": 1}, "outside canvas"),
                                 ({"label_y": 2}, "outside canvas"),
                                 ({"label_x": 495, "label_y": 175}, "covers node")]:
            with self.subTest(changes=changes):
                data = copy.deepcopy(self.data)
                data["edges"][0].update(changes)
                with self.assertRaisesRegex(ValueError, message):
                    RENDER.validate(data)

    def test_no_overwrite_and_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RENDER.write_outputs(self.data, temp, "验证")
            hashes = [p.read_bytes() for p in paths]
            with self.assertRaises(FileExistsError):
                RENDER.write_outputs(self.data, temp, "验证")
            self.assertEqual(hashes, [p.read_bytes() for p in paths])
            RENDER.write_outputs(self.data, temp, "验证", overwrite=True)
            self.assertEqual(hashes, [p.read_bytes() for p in paths])

    def test_bad_basename(self):
        with self.assertRaises(ValueError):
            RENDER.write_outputs(self.data, "unused", "../outside")

    def test_stable_ids_across_views(self):
        first = RENDER.render_mermaid(self.data)
        self.data["nodes"].reverse()
        second = RENDER.render_mermaid(self.data)
        for node in self.data["nodes"]:
            key = RENDER.mermaid_id(node["id"])
            self.assertIn(key + '("', first)
            self.assertIn(key + '("', second)
        ids = ["end", "甲", "u_e794b2", "a b", "a_b", "a\\nb"]
        self.assertEqual(len({RENDER.mermaid_id(key) for key in ids}), len(ids))


if __name__ == "__main__":
    unittest.main()
