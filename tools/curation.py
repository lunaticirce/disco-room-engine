#!/usr/bin/env python3
"""Export and audit the public curation layer without copying private state."""

import argparse
import json
import sqlite3
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCENE_KEYS = (
    "id", "name", "blurb", "home_convs", "points", "exits", "ending",
)
POINT_KEYS = {
    "label", "conv", "node", "show_when", "done_when", "gain_item",
    "set_vars", "advance", "heal", "repeat_heal",
}
EXIT_KEYS = {"label", "to", "show_when", "set_vars"}
ENDING_KEYS = {"show_when", "title", "text", "continue_to"}
CONTINUE_KEYS = {"label", "to"}
COMPAT_KEYS = {
    "party_variables", "hidden_player_lines", "condition_replacements",
    "auto_equip_items", "node_set_vars", "state_repairs",
}

FORBIDDEN_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".mp3", ".wav", ".ogg", ".mp4", ".mov",
}
FORBIDDEN_JSON_KEYS = {"notes", "wall"}


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def reject_unknown(data, allowed, path, kind):
    unknown = set(data) - set(allowed)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"{path}: unknown {kind} keys: {names}")


def sanitize_scene(data, path):
    reject_unknown(data, set(SCENE_KEYS) | {"notes"}, path, "scene")
    if not isinstance(data.get("id"), str) or not data["id"]:
        raise ValueError(f"{path}: scene id must be a non-empty string")
    for point in data.get("points", []):
        reject_unknown(point, POINT_KEYS, path, "point")
    for exit_ in data.get("exits", []):
        reject_unknown(exit_, EXIT_KEYS, path, "exit")
    ending = data.get("ending")
    if ending is not None:
        reject_unknown(ending, ENDING_KEYS, path, "ending")
        for exit_ in ending.get("continue_to", []):
            reject_unknown(exit_, CONTINUE_KEYS, path, "ending exit")
    return {key: data[key] for key in SCENE_KEYS if key in data}


def sanitize_compatibility(data, path):
    reject_unknown(data, COMPAT_KEYS, path, "compatibility")
    return {key: data[key] for key in data}


def export_curation(source, destination, check=False):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    source_scenes = source / "scenes"
    scene_files = sorted(source_scenes.glob("*.json"))
    if not scene_files:
        raise ValueError(f"no scene JSON found under {source_scenes}")

    destination_scenes = destination / "scenes"
    expected_names = {path.name for path in scene_files}
    existing_names = (
        {path.name for path in destination_scenes.glob("*.json")}
        if destination_scenes.is_dir() else set()
    )
    stale = existing_names - expected_names
    if stale:
        names = ", ".join(sorted(stale))
        raise ValueError(
            f"public curation has scenes absent from the source: {names}; "
            "review and remove them deliberately"
        )

    outputs = {}
    for source_path in scene_files:
        scene = sanitize_scene(load_json(source_path), source_path)
        outputs[destination_scenes / source_path.name] = json_text(scene)

    compat_source = source / "compatibility.json"
    if not compat_source.is_file():
        raise ValueError(f"missing compatibility file: {compat_source}")
    compatibility = sanitize_compatibility(
        load_json(compat_source), compat_source,
    )
    outputs[destination / "compatibility.json"] = json_text(compatibility)

    changed = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual != expected:
            changed.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")

    if check and changed:
        names = ", ".join(str(path.relative_to(destination)) for path in changed)
        raise ValueError(f"public curation is out of date: {names}")
    verb = "checked" if check else "exported"
    print(f"{verb} {len(scene_files)} scenes and compatibility.json")


def walk_json_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_keys(child)


def curation_strings(scene, path):
    fields = [("name", scene.get("name")), ("blurb", scene.get("blurb"))]
    fields.extend(("point.label", point.get("label")) for point in scene.get("points", []))
    fields.extend(("exit.label", exit_.get("label")) for exit_ in scene.get("exits", []))
    ending = scene.get("ending") or {}
    fields.extend((("ending.title", ending.get("title")), ("ending.text", ending.get("text"))))
    fields.extend(
        ("ending.continue_to.label", exit_.get("label"))
        for exit_ in ending.get("continue_to", [])
    )
    for field, value in fields:
        if isinstance(value, str) and value.strip():
            yield path, field, value.strip()


def audit_rom(scenes, compatibility, strings, rom_path):
    rom_path = Path(rom_path).resolve()
    connection = sqlite3.connect(f"file:{rom_path}?mode=ro", uri=True)
    try:
        nodes = {
            (conv, node) for conv, node in connection.execute(
                "SELECT conversationid, id FROM temp_table"
            )
        }
        conversations = {conv for conv, _ in nodes}
        rom_text = set()
        for column in ("dialoguetext", "title"):
            rows = connection.execute(
                f"SELECT {column} FROM temp_table WHERE {column} IS NOT NULL"
            )
            rom_text.update(
                value.strip() for (value,) in rows
                if isinstance(value, str) and value.strip()
            )
    finally:
        connection.close()
    matches = [item for item in strings if len(item[2]) >= 20 and item[2] in rom_text]
    if matches:
        locations = ", ".join(f"{path.name}:{field}" for path, field, _ in matches)
        raise ValueError(f"curation contains long exact ROM text: {locations}")

    missing = []
    for scene in scenes.values():
        for conv in scene.get("home_convs", []):
            if conv not in conversations:
                missing.append(f"{scene['id']}.home_convs:{conv}")
        for point in scene.get("points", []):
            conv = point["conv"]
            node = point.get("node")
            if conv not in conversations:
                missing.append(f"{scene['id']}.point:{conv}")
            elif node is not None and (conv, node) not in nodes:
                missing.append(f"{scene['id']}.point:{conv}/{node}")
    for pair in compatibility.get("hidden_player_lines", []):
        if tuple(pair) not in nodes:
            missing.append(f"compatibility.hidden_player_lines:{pair}")
    for key in compatibility.get("node_set_vars", {}):
        try:
            conv, node = (int(value) for value in key.split(":", 1))
        except (TypeError, ValueError):
            missing.append(f"compatibility.node_set_vars:{key}")
            continue
        if (conv, node) not in nodes:
            missing.append(f"compatibility.node_set_vars:{key}")
    if missing:
        raise ValueError(f"curation references missing ROM nodes: {', '.join(missing)}")


def audit_curation(curation, rom_path=None):
    curation = Path(curation).resolve()
    if not curation.is_dir():
        raise ValueError(f"curation directory not found: {curation}")

    forbidden_files = [
        path for path in curation.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    if forbidden_files:
        names = ", ".join(str(path.relative_to(curation)) for path in forbidden_files)
        raise ValueError(f"forbidden binary/content files in curation: {names}")

    scene_files = sorted((curation / "scenes").glob("*.json"))
    if not scene_files:
        raise ValueError("curation has no scenes")
    scenes = {}
    strings = []
    point_count = 0
    exit_count = 0
    for path in scene_files:
        raw = load_json(path)
        forbidden = FORBIDDEN_JSON_KEYS.intersection(walk_json_keys(raw))
        if forbidden:
            raise ValueError(f"{path}: forbidden private keys: {', '.join(sorted(forbidden))}")
        scene = sanitize_scene(raw, path)
        if path.stem != scene["id"]:
            raise ValueError(f"{path}: filename must match scene id {scene['id']!r}")
        scenes[scene["id"]] = scene
        strings.extend(curation_strings(scene, path))
        point_count += len(scene.get("points", []))
        exit_count += len(scene.get("exits", []))
        for conv in scene.get("home_convs", []):
            if not isinstance(conv, int) or isinstance(conv, bool) or conv <= 0:
                raise ValueError(f"{path}: home_convs must contain positive integers")
        for point in scene.get("points", []):
            conv = point.get("conv")
            if not isinstance(conv, int) or isinstance(conv, bool) or conv <= 0:
                raise ValueError(f"{path}: point conv must be a positive integer")
            node = point.get("node")
            if node is not None and (
                not isinstance(node, int) or isinstance(node, bool) or node < 0
            ):
                raise ValueError(f"{path}: point node must be a non-negative integer")

    for path in scene_files:
        scene = scenes[path.stem]
        targets = [exit_["to"] for exit_ in scene.get("exits", [])]
        ending = scene.get("ending") or {}
        targets.extend(exit_["to"] for exit_ in ending.get("continue_to", []))
        missing = sorted(set(targets) - set(scenes))
        if missing:
            raise ValueError(f"{path}: exits target missing scenes: {', '.join(missing)}")

    compat_path = curation / "compatibility.json"
    compatibility = load_json(compat_path)
    forbidden = FORBIDDEN_JSON_KEYS.intersection(walk_json_keys(compatibility))
    if forbidden:
        raise ValueError(f"{compat_path}: forbidden private keys: {', '.join(sorted(forbidden))}")
    sanitize_compatibility(compatibility, compat_path)

    for profile_path in sorted((curation / "profiles").glob("*.json")):
        profile = load_json(profile_path)
        forbidden = FORBIDDEN_JSON_KEYS.intersection(walk_json_keys(profile))
        if forbidden:
            raise ValueError(f"{profile_path}: forbidden private keys: {', '.join(sorted(forbidden))}")
        save_path = profile.get("save")
        if not isinstance(save_path, str) or Path(save_path).is_absolute():
            raise ValueError(f"{profile_path}: save must be a relative path")

    if rom_path:
        audit_rom(scenes, compatibility, strings, rom_path)
    print(
        f"curation audit passed: {len(scenes)} scenes, "
        f"{point_count} points, {exit_count} exits"
    )


def audit_wheel(wheel_path):
    wheel_path = Path(wheel_path).resolve()
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
    forbidden = [
        name for name in names
        if name.startswith("curation/")
        or Path(name).suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    if forbidden:
        raise ValueError(f"wheel contains content-layer files: {', '.join(forbidden)}")
    print(f"wheel audit passed: {wheel_path.name}, {len(names)} files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("source", help="private content-project root")
    export_parser.add_argument("destination", nargs="?", default=ROOT / "curation")
    export_parser.add_argument("--check", action="store_true")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("curation", nargs="?", default=ROOT / "curation")
    audit_parser.add_argument("--rom", help="optional local ROM for exact-text checks")

    wheel_parser = subparsers.add_parser("audit-wheel")
    wheel_parser.add_argument("wheel")

    args = parser.parse_args()
    if args.command == "export":
        export_curation(args.source, args.destination, check=args.check)
    elif args.command == "audit":
        audit_curation(args.curation, rom_path=args.rom)
    else:
        audit_wheel(args.wheel)


if __name__ == "__main__":
    main()
