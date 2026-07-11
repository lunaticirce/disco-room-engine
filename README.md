# Disco Room Engine

Disco Room Engine is a local, data-driven runtime for condition-heavy dialogue
graphs. It resolves graph traversal, state predicates, 2d6 checks, userscript
effects, per-player saves, health and morale, a world clock, and hand-curated
room menus above the raw graph.

The engine is intentionally separate from content. This repository ships no
Disco Elysium dialogue, extracted database, save, or player journal. See
`NOTICE.md` before connecting a third-party content project.

## Install

```sh
python3 -m pip install -e .
```

## Try the synthetic room

The example is original test content. Its tiny SQLite graph is generated on
your machine and ignored by Git.

```sh
python3 examples/minimal/build_rom.py
disco-room --project examples/minimal --profile demo start 1
```

Then use `choose N`, `beat`, `scene`, `look N`, `where`, and `status`.

## Use a content project

A content project owns its ROM, profiles, scenes, and saves:

```text
my-room/
├── data/
│   └── disco-rom.db
├── profiles/
│   └── demo.json
└── scenes/
    └── room.json
```

Point the engine at it explicitly:

```sh
disco-room --project /path/to/my-room --profile demo status
```

The equivalent environment variables are:

- `DISCO_ROOM_PROJECT`: content-project root
- `DISCO_ROOM_ROM`: optional ROM path override
- `DISCO_ROOM_PROFILES`: optional profile-directory override
- `DISCO_ROOM_DEFAULT_PROFILE`: default profile name
- `DISCO_PROFILE`: active profile name

See `docs/content-project.md` for the JSON contracts and runtime ownership
boundary.

## Verify

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples
git diff --check
```

## Status

This is an alpha extraction of a working private room engine. The command-line
surface is stable enough for local play; package APIs and content schemas may
still change before 1.0.
