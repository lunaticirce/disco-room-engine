import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CURATION = ROOT / "curation"
sys.path.insert(0, str(SRC))

from disco_room import room


def load_curation_tool():
    path = ROOT / "tools" / "curation.py"
    spec = importlib.util.spec_from_file_location("curation_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def conditions_in(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("show_when", "done_when") and isinstance(child, str):
                yield child
            yield from conditions_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from conditions_in(child)


class CurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_curation_tool()
        cls.scene_files = sorted((CURATION / "scenes").glob("*.json"))

    def test_public_curation_contract_and_counts(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.tool.audit_curation(CURATION)
        self.assertIn("25 scenes, 128 points, 62 exits", output.getvalue())

        scenes = [json.loads(path.read_text()) for path in self.scene_files]
        self.assertEqual(len(scenes), 25)
        self.assertEqual(sum(len(scene.get("home_convs", [])) for scene in scenes), 136)

    def test_all_scene_conditions_parse_without_fail_open(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            for path in self.scene_files:
                scene = json.loads(path.read_text())
                for condition in conditions_in(scene):
                    room.eval_condition(
                        condition,
                        {},
                        {},
                        clock={"day": 2, "minute": 21 * 60},
                    )
        self.assertEqual(stderr.getvalue(), "")

    def test_export_strips_only_notes_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            destination = Path(tmp) / "destination"
            (source / "scenes").mkdir(parents=True)
            shutil.copy(CURATION / "compatibility.json", source / "compatibility.json")
            scene = {
                "id": "room",
                "name": "房间",
                "notes": ["private review history"],
                "points": [{"label": "门", "conv": 1}],
                "exits": [],
            }
            source_scene = source / "scenes" / "room.json"
            source_scene.write_text(json.dumps(scene, ensure_ascii=False))

            with contextlib.redirect_stdout(io.StringIO()):
                self.tool.export_curation(source, destination)
            exported = json.loads((destination / "scenes" / "room.json").read_text())
            self.assertNotIn("notes", exported)
            self.assertEqual(exported["points"], scene["points"])

            scene["points"][0]["unknown_runtime_key"] = True
            source_scene.write_text(json.dumps(scene, ensure_ascii=False))
            with self.assertRaisesRegex(ValueError, "unknown point keys"):
                self.tool.export_curation(source, destination)

    def test_heal_config_validation_rejects_misconfigured_points(self):
        tool = self.tool
        base = {"id": "room", "name": "room", "points": [], "exits": []}

        def expect_bad(point, needle):
            with self.assertRaisesRegex(ValueError, needle):
                tool.sanitize_scene({**base, "points": [point]}, "room.json")

        # heal: empty dict / unknown pool / non-positive / bool / wrong type
        expect_bad({"label": "a", "conv": 1, "heal": {}}, "heal must not be empty")
        expect_bad({"label": "a", "conv": 1, "heal": {"stamina": 1}}, "unknown pool")
        expect_bad({"label": "a", "conv": 1, "heal": {"health": 0}}, "positive int")
        expect_bad({"label": "a", "conv": 1, "heal": {"health": True}}, "positive int")
        expect_bad({"label": "a", "conv": 1, "heal": 5}, "heal must be")
        # repeat_heal: dict-only (not "full"), and requires node
        expect_bad(
            {"label": "a", "conv": 1, "node": 1, "repeat_heal": "full"},
            "repeat_heal must be",
        )
        expect_bad(
            {"label": "a", "conv": 1, "repeat_heal": {"health": 1}},
            "repeat_heal requires `node`",
        )
        # mutual exclusivity: a point can't carry both heal kinds
        expect_bad(
            {
                "label": "a", "conv": 1, "node": 1,
                "heal": {"health": 1}, "repeat_heal": {"health": 1},
            },
            "both heal and repeat_heal",
        )
        # null must not bypass presence checks: point.get() returns None for both
        # an absent key and an explicit null, so presence is tested with `in`,
        # then the type check rejects the null value.
        expect_bad({"label": "a", "conv": 1, "heal": None}, "heal must be")
        expect_bad({"label": "a", "conv": 1, "repeat_heal": None}, "repeat_heal must be")
        expect_bad(
            {
                "label": "a", "conv": 1, "node": 1,
                "heal": None, "repeat_heal": {"health": 1},
            },
            "both heal and repeat_heal",
        )

        # valid configs pass without raising
        for ok in (
            {"label": "a", "conv": 1, "heal": "full"},
            {"label": "a", "conv": 1, "heal": {"morale": 2, "health": 2}},
            {"label": "a", "conv": 1, "node": 1, "repeat_heal": {"health": 1}},
        ):
            tool.sanitize_scene({**base, "points": [ok]}, "room.json")

    def test_bundled_profile_is_anonymous_and_writes_only_ignored_state(self):
        profile = json.loads((CURATION / "profiles" / "player.json").read_text())
        self.assertEqual(profile["id"], "player")
        self.assertFalse(Path(profile["save"]).is_absolute())
        self.assertTrue(profile["save"].startswith("data/"))
        self.assertNotIn("wall", profile)
        self.assertNotIn("notes", profile)


if __name__ == "__main__":
    unittest.main()
