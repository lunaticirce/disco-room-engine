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
        self.assertIn("22 scenes, 110 points, 53 exits", output.getvalue())

        scenes = [json.loads(path.read_text()) for path in self.scene_files]
        self.assertEqual(len(scenes), 22)
        self.assertEqual(sum(len(scene.get("home_convs", [])) for scene in scenes), 100)

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

    def test_bundled_profile_is_anonymous_and_writes_only_ignored_state(self):
        profile = json.loads((CURATION / "profiles" / "player.json").read_text())
        self.assertEqual(profile["id"], "player")
        self.assertFalse(Path(profile["save"]).is_absolute())
        self.assertTrue(profile["save"].startswith("data/"))
        self.assertNotIn("wall", profile)
        self.assertNotIn("notes", profile)


if __name__ == "__main__":
    unittest.main()
