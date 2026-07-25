import importlib.util
import contextlib
import io
import os
import shutil
import sqlite3
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

    def test_new_save_creates_its_missing_parent_directory(self):
        import json
        profile = {
            "id": "nested",
            "name": "Nested Save",
            "save": "private-state/nested/player-save.db",
            "attrs": room.DEFAULT_ATTRS,
        }
        profile_path = self.project / "profiles" / "nested.json"
        profile_path.write_text(json.dumps(profile))
        save_parent = self.project / "private-state"
        shutil.rmtree(save_parent, ignore_errors=True)

        room.configure_profile("nested")
        room.init_save(1, node=1)

        self.assertTrue((save_parent / "nested" / "player-save.db").is_file())

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
        self.assertNotIn("没有房间菜单", result.stdout)  # has a home scene → no nav hint

    def test_no_scene_conversation_prints_navigation_hint(self):
        # A conversation no scene lists (like the curated opening dream) should
        # print the one-time navigation hint on entry. Restore the scene after
        # so other tests in the class still see it.
        scene_path = self.project / "scenes" / "borrowed_room.json"
        saved = scene_path.read_text(encoding="utf-8")
        try:
            scene_path.unlink()
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
            self.assertIn("没有房间菜单", result.stdout)
        finally:
            scene_path.write_text(saved, encoding="utf-8")

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


def _rest_save(morale_cur=5, morale_max=5, health_cur=1, health_max=2):
    """An in-memory save connection with a seeded vitality row, for rest-heal
    tests. Mirrors the live vitality schema (room._VITALITY_TBL); apply_rest_heal
    only touches the vitality table, so no other state is needed."""
    connection = sqlite3.connect(":memory:")
    connection.execute(room._VITALITY_TBL)
    connection.execute(
        "INSERT INTO vitality VALUES(1,?,?,?,?)",
        (morale_cur, morale_max, health_cur, health_max),
    )
    connection.commit()
    return connection


class RestHealTests(unittest.TestCase):
    """Public contract for scenes.apply_rest_heal — the rest-heal tied to an
    `advance` point (bed → morning, bench → night) that restores morale + health
    UNCONDITIONALLY on every rest. This is the systematic vitality restore that
    sleep otherwise lacks. See docs/content-project.md (`heal`) and
    scenes.apply_rest_heal."""

    def test_heals_every_time_unconditional(self):
        # No fired-gating: every rest heals. Call twice on a fresh save and both
        # calls restore (contrast with repeat_heal, whose first call is a no-op).
        c = _rest_save(morale_cur=1, morale_max=5, health_cur=0, health_max=2)
        with contextlib.redirect_stdout(io.StringIO()):
            first = scenes.apply_rest_heal(c, {"morale": 2, "health": 2})
            second = scenes.apply_rest_heal(c, {"morale": 2, "health": 2})
        self.assertEqual(first, {"morale": 2, "health": 2})
        self.assertEqual(second, {"morale": 2, "health": 0})  # health already at max
        vit = room.load_vitality(c)
        self.assertEqual((vit["morale_cur"], vit["health_cur"]), (5, 2))

    def test_caps_at_max(self):
        c = _rest_save(morale_cur=5, morale_max=5, health_cur=2, health_max=2)
        with contextlib.redirect_stdout(io.StringIO()):
            delta = scenes.apply_rest_heal(c, {"morale": 2, "health": 2})
        self.assertEqual(delta, {"morale": 0, "health": 0})  # at max → no over-heal

    def test_full_restores_to_max(self):
        c = _rest_save(morale_cur=1, morale_max=5, health_cur=0, health_max=2)
        with contextlib.redirect_stdout(io.StringIO()):
            delta = scenes.apply_rest_heal(c, "full")
        self.assertEqual(delta, {"morale": 4, "health": 2})
        vit = room.load_vitality(c)
        self.assertEqual((vit["morale_cur"], vit["health_cur"]), (5, 2))

    def test_invalid_spec_rejected(self):
        c = _rest_save()
        for bad in ("morning", 5, ["morale", 1]):
            with self.assertRaises(ValueError, msg=f"bad={bad!r}"):
                scenes.apply_rest_heal(c, bad)

    def test_non_positive_amount_rejected(self):
        c = _rest_save()
        for bad in (0, -1, 1.5, True, "1"):
            with self.assertRaises(ValueError, msg=f"bad={bad!r}"):
                scenes.apply_rest_heal(c, {"health": bad})


if __name__ == "__main__":
    unittest.main()
