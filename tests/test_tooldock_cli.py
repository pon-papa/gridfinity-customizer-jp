# -*- coding: utf-8 -*-
"""tooldock_cli.py（ToolDock Connector v1 の入口）の試験。

    .venv\\Scripts\\python.exe -B tests\\test_tooldock_cli.py

出力はすべて OS の一時フォルダーに作り、試験の後に消す。見本プリセットは読むだけ。
ToolDock・MCP は使わない（入口は単体の JSON CLI として動く）。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tooldock_cli.py"
MANIFEST = ROOT / "tooldock.tool.json"
SAMPLE = ROOT / "presets" / "sample_units_plus_mm.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import tooldock_cli  # noqa: E402


def run(command: str, payload, raw: str | None = None):
    data = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
    proc = subprocess.run([sys.executable, "-B", str(CLI), command, "--input-json", "-"],
                          input=data.encode("utf-8"), capture_output=True, cwd=str(ROOT),
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=600)
    lines = proc.stdout.decode("utf-8").strip().splitlines()
    assert len(lines) == 1, (proc.stdout, proc.stderr.decode("utf-8", "replace")[-2000:])
    return proc.returncode, json.loads(lines[0])


def fingerprint(folder: Path) -> dict:
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(folder.iterdir()) if p.is_file()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gridfinity_cli_test_"))
        # 日本語・空白・em dash・&・括弧を含む保存先
        self.out = self.tmp / "出力 — 箱 & 枠 (試験)"
        self.out.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def generate(self, **extra):
        args = {"name": "試験 箱", "output_folder": str(self.out), "width_mm": 103.0, "depth_mm": 71.0}
        args.update(extra)
        return run("generate", args)


class ManifestTest(unittest.TestCase):
    def test_manifest_matches_the_cli(self):
        spec = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(spec["connector_version"], 1)
        self.assertEqual(spec["interface"]["entry"], CLI.name)
        commands = {a["command"] for a in spec["actions"]}
        self.assertEqual(commands, set(tooldock_cli.COMMANDS))
        by_name = {a["name"]: a for a in spec["actions"]}
        gen = by_name["generate"]["input_schema"]
        self.assertEqual(set(gen["properties"]), tooldock_cli.GENERATE_KEYS)
        self.assertFalse(gen["additionalProperties"])
        pre = by_name["generate_from_preset"]["input_schema"]
        self.assertEqual(set(pre["properties"]), tooldock_cli.PRESET_KEYS)
        props = gen["properties"]
        self.assertEqual(tuple(props["shape"]["enum"]), tooldock_cli.SHAPES)
        self.assertEqual(tuple(props["anchor"]["enum"]), tooldock_cli.ANCHORS)
        self.assertEqual(tuple(props["structure_profile"]["enum"]), tooldock_cli.PROFILES)
        self.assertEqual(tuple(props["formats"]["items"]["enum"]), tooldock_cli.FORMATS)
        for key, (low, high) in tooldock_cli.LIMITS.items():
            self.assertEqual((props[key]["minimum"], props[key]["maximum"]), (low, high), key)
        for key, value in tooldock_cli.COMMON_DEFAULTS.items():
            prop = props["shape" if key == "shape" else key]
            self.assertEqual(prop.get("default"), value, key)
        # 構造プロファイルで変わる値には既定値を書かない（ToolDock が先に埋めてしまうため）
        for key in ("wall_thickness_mm", "floor_thickness_mm", "corner_radius_mm",
                    "base_frame_style", "anti_warp_ears"):
            self.assertNotIn("default", props[key], key)
        self.assertEqual(by_name["get_capabilities"]["access"], "read")
        self.assertEqual(by_name["generate"]["access"], "write")
        self.assertEqual(props["output_folder"]["x-path"], "output_folder")
        self.assertEqual(pre["properties"]["preset"]["x-path"], "media_file")

    def test_the_app_does_not_depend_on_tooldock(self):
        for path in list((ROOT / "src").rglob("*.py")) + [ROOT / "app.py", CLI]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import tooldock", text, path)
            self.assertNotIn("import mcp", text, path)
            self.assertNotIn("tooldock.tool.json", text if path != CLI else "", path)


class CapabilitiesTest(unittest.TestCase):
    def test_capabilities(self):
        code, reply = run("capabilities", {})
        self.assertEqual(code, 0)
        res = reply["result"]
        self.assertEqual(set(res["shapes"]), {"box", "tile", "baseplate_only"})
        self.assertIn("3mf", res["formats"])
        self.assertIn("stl", res["formats"])
        self.assertNotIn("step", res["formats"])
        self.assertEqual(res["structure_profiles"]["robust"]["wall_thickness_mm"], 1.2)

    def test_capabilities_takes_no_arguments(self):
        code, reply = run("capabilities", {"x": 1})
        self.assertEqual(reply["error"]["code"], "invalid_arguments")


class GenerateTest(Base):
    def test_box_3mf_and_stl(self):
        code, reply = self.generate(formats=["3mf", "stl"])
        self.assertEqual(code, 0, reply)
        res = reply["result"]
        self.assertEqual(res["status"], "READY")
        names = sorted(Path(f["path"]).name for f in res["files"])
        self.assertEqual(names, sorted([
            "試験 箱_container.3mf", "試験 箱_baseplate.3mf", "試験 箱_set.3mf",
            "試験 箱_container.stl", "試験 箱_baseplate.stl",
            "試験 箱_parameters.json", "試験 箱_validation.json", "試験 箱_layout.svg"]))
        for f in res["files"]:
            p = Path(f["path"])
            self.assertEqual(p.parent, self.out)
            self.assertEqual(p.stat().st_size, f["bytes"])
        self.assertEqual(res["finished_mm"], [102.6, 70.6, 21.0])
        self.assertTrue(res["watertight"])
        # 3MF は ZIP、STL はバイナリの三角形数と大きさが合う
        import zipfile
        with zipfile.ZipFile(self.out / "試験 箱_set.3mf") as z:
            self.assertIn("3D/3dmodel.model", z.namelist())
        stl = (self.out / "試験 箱_container.stl").read_bytes()
        count = int.from_bytes(stl[80:84], "little")
        self.assertEqual(len(stl), 84 + 50 * count)
        # parameters.json には一時フォルダーではなく保存先が残る
        params = json.loads((self.out / "試験 箱_parameters.json").read_text(encoding="utf-8"))
        self.assertEqual(params["output_dir"], str(self.out))
        self.assertEqual(params["structure_profile"], "lightweight")
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.endswith(".part")], [])

    def test_profiles_follow_the_gui(self):
        code, reply = self.generate(structure_profile="robust", generate_baseplate=False)
        self.assertEqual(code, 0, reply)
        params = json.loads((self.out / "試験 箱_parameters.json").read_text(encoding="utf-8"))
        self.assertEqual((params["wall_thickness_mm"], params["floor_thickness_mm"], params["corner_radius_mm"],
                          params["base_frame_style"], params["anti_warp_ears"]),
                         (1.2, 1.2, 1.5, "robust", False))
        self.assertIsNone(reply["result"]["meshes"].get("baseplate"))

    def test_units_plus_mm(self):
        code, reply = self.generate(width_mm=None) if False else run("generate", {
            "name": "units", "output_folder": str(self.out), "dimension_input_mode": "units_plus_mm",
            "width_units": 2, "width_extra_mm": 29.0, "depth_units": 4})
        self.assertEqual(code, 0, reply)
        self.assertEqual(reply["result"]["requested_mm"], [113.0, 168.0, 21.0])

    def test_tile_and_baseplate_only(self):
        code, reply = self.generate(name="tile", shape="tile", height_mm=7, wall_left=False)
        self.assertEqual(code, 0, reply)
        self.assertTrue(reply["result"]["notes"])
        code, reply = self.generate(name="frame", shape="baseplate_only")
        self.assertEqual(code, 0, reply)
        kinds = {f["kind"] for f in reply["result"]["files"]}
        self.assertNotIn("container", kinds)
        self.assertIn("baseplate", kinds)

    def test_step_is_not_offered(self):
        """STEP は未検証なので、CadQuery の有無にかかわらず入口からは出さない。"""
        code, reply = self.generate(name="step", formats=["step"])
        self.assertEqual(reply["error"]["code"], "invalid_arguments")
        preset = json.loads(SAMPLE.read_text(encoding="utf-8"))
        preset["export_step"] = True
        p = self.tmp / "step preset.json"
        p.write_text(json.dumps(preset, ensure_ascii=False), encoding="utf-8")
        code, reply = run("generate_from_preset", {"preset": str(p), "output_folder": str(self.out)})
        self.assertEqual(reply["error"]["code"], "step_not_offered")
        self.assertEqual(list(self.out.iterdir()), [])
        caps = run("capabilities", {})[1]["result"]
        self.assertEqual((caps["formats"], caps["step_available"], caps["step"]["offered"]),
                         (["3mf", "stl"], False, False))

    def test_same_geometry_as_the_existing_cli(self):
        """入口は画面・既存 CLI と同じ生成処理を使う（STL がバイト一致）。"""
        preset = json.loads(SAMPLE.read_text(encoding="utf-8"))
        preset.update(output_dir=str(self.tmp / "cli"), export_stl=True)
        p = self.tmp / "preset.json"
        p.write_text(json.dumps(preset, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, "-B", "-m", "gridfinity_customizer.cli", str(p)], check=True,
                       capture_output=True, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")))
        code, reply = run("generate_from_preset", {"preset": str(p), "output_folder": str(self.out)})
        self.assertEqual(code, 0, reply)
        for kind in ("container", "baseplate"):
            name = f"{preset['name']}_{kind}.stl"
            self.assertEqual((self.tmp / "cli" / name).read_bytes(), (self.out / name).read_bytes(), name)


class ProtectionTest(Base):
    def test_overwrite_is_refused_by_default(self):
        self.assertEqual(self.generate()[0], 0)
        before = fingerprint(self.out)
        code, reply = self.generate()
        self.assertEqual(reply["error"]["code"], "output_exists")
        self.assertEqual(fingerprint(self.out), before)
        code, reply = self.generate(overwrite=True)
        self.assertEqual(code, 0, reply)

    def test_one_clash_writes_nothing(self):
        (self.out / "試験 箱_layout.svg").write_text("mine", encoding="utf-8")
        code, reply = self.generate()
        self.assertEqual(reply["error"]["code"], "output_exists")
        self.assertEqual([p.name for p in self.out.iterdir()], ["試験 箱_layout.svg"])
        self.assertEqual((self.out / "試験 箱_layout.svg").read_text(encoding="utf-8"), "mine")

    def test_preset_is_read_only_and_its_output_dir_is_ignored(self):
        src = self.tmp / "プリセット — 棚 & 箱 (見本)"
        src.mkdir()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        preset = json.loads(SAMPLE.read_text(encoding="utf-8"))
        preset["output_dir"] = str(elsewhere)
        p = src / "見本 プリセット.json"
        p.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8")
        before = fingerprint(src)
        code, reply = run("generate_from_preset", {"preset": str(p), "output_folder": str(self.out)})
        self.assertEqual(code, 0, reply)
        self.assertEqual(fingerprint(src), before)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertTrue(all(Path(f["path"]).parent == self.out for f in reply["result"]["files"]))

    def test_output_folder_must_be_absolute_existing_and_outside_the_app(self):
        cases = [("relative", "invalid_arguments"),
                 (str(self.tmp / "無い"), "invalid_output"),
                 (str(ROOT / "src"), "invalid_output"),
                 (str(ROOT), "invalid_output")]
        for folder, expected in cases:
            code, reply = self.generate(output_folder=folder)
            self.assertEqual(reply["error"]["code"], expected, folder)
        self.assertFalse(any((ROOT / "src").glob("*.3mf")))

    def test_invalid_dimensions(self):
        cases = [dict(height_mm=3.0), dict(wall_thickness_mm=0.1), dict(width_mm=700.0),
                 dict(width_mm=-1.0), dict(width_mm="103"), dict(corner_radius_mm=25.0),
                 dict(ear_length_mm=40.0), dict(clearance_total_mm=-0.1),
                 dict(structure_profile="robust", anti_warp_ears=True),
                 dict(shape="baseplate_only", generate_baseplate=False),
                 dict(shape="cube"), dict(anchor="center"), dict(formats=[]),
                 dict(formats=["3mf", "3mf"]), dict(formats=["obj"]),
                 dict(name=""), dict(name="x" * 61), dict(name="CON"), dict(name="a\u0007b")]
        for extra in cases:
            code, reply = self.generate(**extra)
            self.assertEqual(code, 1, extra)
            self.assertIn(reply["error"]["code"], {"invalid_arguments", "invalid_dimensions"}, extra)
        # アプリ自身の検査（完成寸法が小さすぎる）
        code, reply = self.generate(width_mm=5.2, clearance_total_mm=0.4)
        self.assertEqual(reply["error"]["code"], "invalid_dimensions")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_mixed_dimension_modes_are_refused(self):
        code, reply = run("generate", {"name": "x", "output_folder": str(self.out),
                                       "width_mm": 100, "depth_mm": 100, "width_units": 2})
        self.assertEqual(reply["error"]["code"], "invalid_arguments")
        code, reply = run("generate", {"name": "x", "output_folder": str(self.out),
                                       "dimension_input_mode": "units_plus_mm", "width_units": 1.5,
                                       "depth_units": 1})
        self.assertEqual(reply["error"]["code"], "invalid_arguments")
        code, reply = run("generate", {"name": "x", "output_folder": str(self.out)})
        self.assertEqual(reply["error"]["code"], "invalid_arguments")

    def test_bad_presets(self):
        bad = {"unknown key.json": json.dumps({"name": "x", "shell": "dir"}),
               "not json.json": "{not json",
               "bad walls.json": json.dumps({"name": "x", "walls": 3}),
               "string height.json": json.dumps({"name": "x", "height_mm": "21"})}
        for name, text in bad.items():
            p = self.tmp / name
            p.write_text(text, encoding="utf-8")
            code, reply = run("generate_from_preset", {"preset": str(p), "output_folder": str(self.out)})
            self.assertIn(reply["error"]["code"], {"invalid_preset", "invalid_dimensions"}, name)
        big = self.tmp / "big.json"
        big.write_text(json.dumps({"name": "x", "pad": "x" * 300_000}), encoding="utf-8")
        code, reply = run("generate_from_preset", {"preset": str(big), "output_folder": str(self.out)})
        self.assertEqual(reply["error"]["code"], "invalid_preset")
        code, reply = run("generate_from_preset", {"preset": str(self.tmp / "x.txt"), "output_folder": str(self.out)})
        self.assertEqual(reply["error"]["code"], "invalid_arguments")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_malformed_input(self):
        self.assertEqual(run("generate", None, raw="{not json")[1]["error"]["code"], "usage_error")
        self.assertEqual(run("generate", None, raw="[1, 2]")[1]["error"]["code"], "usage_error")
        self.assertEqual(self.generate(shell="dir")[1]["error"]["code"], "invalid_arguments")
        proc = subprocess.run([sys.executable, "-B", str(CLI), "run_command", "--input-json", "-"],
                              input=b"{}", capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "usage_error")
        proc = subprocess.run([sys.executable, "-B", str(CLI), "generate", "--input-json", "x.json"],
                              input=b"{}", capture_output=True)
        self.assertEqual(json.loads(proc.stdout)["error"]["code"], "usage_error")


if __name__ == "__main__":
    unittest.main(verbosity=1)
