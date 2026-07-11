import importlib.util
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from disco_room import room, scenes


def load_example_builder():
    path = ROOT / "examples" / "minimal" / "build_rom.py"
    spec = importlib.util.spec_from_file_location("minimal_rom_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.project = Path(cls.tmp.name) / "minimal"
        shutil.copytree(ROOT / "examples" / "minimal", cls.project)
        rom_path = cls.project / "data" / "disco-rom.db"
        rom_path.unlink(missing_ok=True)
        load_example_builder().build_rom(rom_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        save = self.project / "data" / "demo-save.db"
        if save.exists():
            save.unlink()
        room.configure_project(self.project)
        room.configure_profile("demo")
        scenes._SCENES_CACHE = None

    def test_project_configuration_owns_content_paths(self):
        self.assertEqual(room.PROJ, str(self.project))
        self.assertEqual(room.ROM, str(self.project / "data" / "disco-rom.db"))
        self.assertEqual(room.PROFILES, str(self.project / "profiles"))
        self.assertEqual(room.SAVE, str(self.project / "data" / "demo-save.db"))

    def test_synthetic_graph_initializes_save_and_exposes_choices(self):
        room.init_save(1, node=1)
        c = room.save()
        variables = room.load_vars(c)
        inventory = room.load_inventory(c)
        fired = room.load_fired(c)
        c.close()
        rc = room.rom()
        npc, options = room.beat_options(rc, 1, 1, variables, inventory, fired=fired)
        rc.close()
        self.assertEqual(npc, [("Lamp", "The lamp hums over a notebook with one clean page.")])
        self.assertEqual(options, [(1, 2), (1, 3)])
        self.assertFalse(variables["demo.notebook_open"])

    def test_userscript_mutates_synthetic_state(self):
        variables = {"demo.notebook_open": False}
        room.apply_userscript(
            'SetVariableValue("demo.notebook_open", true)', variables, {}
        )
        self.assertTrue(variables["demo.notebook_open"])

    def test_condition_ast_rejects_python_object_access(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = room.eval_condition(
                "Variable.__class__.__mro__[1].__subclasses__()", {}, {}
            )
        self.assertTrue(result)  # malformed conditions retain fail-open semantics
        self.assertIn("[cond fail-open]", stderr.getvalue())
        self.assertIn("condition calls must target a named predicate", stderr.getvalue())

    def test_content_compatibility_rules_are_data_driven(self):
        room.COMPAT = {
            "hidden_player_lines": [[1, 2]],
            "condition_replacements": {
                "broken_name": 'Variable["demo.notebook_open"]'
            },
            "auto_equip_items": ["demo_tool"],
            "node_set_vars": {"1:4": {"demo.node_effect": True}},
        }
        self.assertEqual(
            room.normalize_condition_expr("broken_name == true"),
            'Variable["demo.notebook_open"] == true',
        )
        inventory = {}
        room.apply_userscript('GainItem("demo_tool")', {}, inventory)
        self.assertTrue(inventory["demo_tool"])

        rc = room.rom()
        self.assertFalse(room.option_available(rc, 1, 2, {}))
        variables = {}
        fire = room.make_fire(rc, variables, {}, set())
        fire(1, 4)
        rc.close()
        self.assertTrue(variables["demo.node_effect"])

    def test_scene_layer_reads_the_content_project(self):
        scene = scenes.load_scene("borrowed_room")
        self.assertEqual(scene["id"], "borrowed_room")
        self.assertEqual(scenes.home_scene_for(1), "borrowed_room")
        items = scenes.menu_items(scene, {}, {})
        self.assertEqual(items[0]["conv"], 1)

    def test_cli_accepts_project_and_profile(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "disco_room",
                "--project",
                str(self.project),
                "--profile",
                "demo",
                "start",
                "1",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("The lamp hums over a notebook", result.stdout)
        self.assertIn("Open the notebook.", result.stdout)

    def test_coverage_runs_from_packaged_cli(self):
        room.init_save(1, node=1)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "disco_room",
                "--project",
                str(self.project),
                "--profile",
                "demo",
                "coverage",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("〔coverage", result.stdout)
        self.assertIn("没有活跃任务", result.stdout)

    def test_help_command_prints_chinese_help(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        for key in ("DISCO_ROOM_PROJECT", "DISCO_ROOM_PROFILES", "DISCO_PROFILE"):
            env.pop(key, None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "disco_room",
                "help",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tmp.name,
        )
        self.assertIn("命令一览", result.stdout)
        self.assertIn("start", result.stdout)
        # the old private-engine docstring must not leak into help output
        self.assertNotIn("SAVE :", result.stdout)
        self.assertNotIn("community-extracted game logic", result.stdout)

    def test_profile_example_is_relative_and_synthetic(self):
        import json
        raw = json.loads((
            ROOT / "examples" / "minimal" / "profiles" / "demo.json"
        ).read_text())
        self.assertEqual(raw["save"], "data/demo-save.db")
        self.assertFalse(Path(raw["save"]).is_absolute())

    def test_public_history_tracks_no_database(self):
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "*.db"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(tracked, "")


if __name__ == "__main__":
    unittest.main()
