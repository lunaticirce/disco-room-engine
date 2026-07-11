# Content project contract

The engine package is read-only with respect to content definitions. A content
project supplies the graph database, profile definitions, and scene JSON. Only
the selected profile save is mutated during play.

## Layout

```text
project/
├── data/disco-rom.db
├── compatibility.json
├── profiles/<profile>.json
└── scenes/<scene>.json
```

Paths in a profile are relative to the project root unless absolute.

## Compatibility rules

Content-specific extractor repairs and graph exceptions live outside the
engine in `compatibility.json`:

```json
{
  "party_variables": {
    "kim": "story.partner_present",
    "cuno": "story.alternate_partner_present"
  },
  "hidden_player_lines": [[12, 34]],
  "condition_replacements": {
    "broken_extractor_name": "Variable[\"canonical.name\"]"
  },
  "auto_equip_items": ["demo_tool"],
  "node_set_vars": {
    "12:56": {"story.missing_effect": true}
  },
  "state_repairs": [
    {
      "when": {"story.old_evidence": true},
      "unless": {"story.repaired": true},
      "set": {"story.repaired": true}
    }
  ]
}
```

All keys are optional. This keeps quirks of one graph or extractor out of the
runtime while preserving exact behavior for that content pack.

## Profile

```json
{
  "id": "demo",
  "name": "Demo Detective",
  "save": "data/demo-save.db",
  "attrs": {
    "Intellect": 4,
    "Psyche": 4,
    "Physique": 2,
    "Motorics": 2
  },
  "signature_skill": "Inland Empire",
  "notes": []
}
```

## Scene

```json
{
  "id": "borrowed_room",
  "name": "Borrowed Room",
  "blurb": "A lamp hums beside a blank notebook.",
  "home_convs": [1],
  "points": [
    {"label": "The humming lamp", "conv": 1}
  ],
  "exits": []
}
```

Supported scene point keys are `label`, `conv`, `node`, `show_when`,
`done_when`, `gain_item`, `set_vars`, `advance`, and `repeat_heal`. Exits use
`label`, `to`, `show_when`, and `set_vars`. An ending may define
`show_when`, `title`, `text`, and `continue_to` exits.

## Database

The runtime expects SQLite tables named `actors`, `temp_table`, `dlinks`,
`variables`, `checks`, and `modifiers`. The synthetic builder under
`examples/minimal` is the executable schema example.
