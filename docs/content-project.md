# 内容项目约定

引擎包对内容定义是只读的。内容项目负责提供对话图数据库、玩家档案定义和场景 JSON。游玩过程中只有当前选中档案的存档会被写入。

## 目录结构

```text
project/
├── data/disco-rom.db
├── compatibility.json
├── profiles/<profile>.json
└── scenes/<scene>.json
```

档案中的路径除非是绝对路径，否则都相对于项目根目录。

## 兼容性规则

针对特定内容的提取器修补与对话图例外，都放在引擎之外的 `compatibility.json` 里：

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

所有字段都是可选的。这样能把某一个对话图或提取器的怪癖挡在运行时之外，同时仍为该内容包保留完全一致的行为。

## 玩家档案（Profile）

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

## 场景（Scene）

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

场景交互点（point）支持的字段有 `label`、`conv`、`node`、`show_when`、`done_when`、`gain_item`、`set_vars`、`advance` 和 `repeat_heal`。出口（exit）使用 `label`、`to`、`show_when` 和 `set_vars`。一个结局（ending）可以定义 `show_when`、`title`、`text` 以及 `continue_to` 出口。

## 数据库

运行时期望 SQLite 中存在以下数据表：`actors`、`temp_table`、`dlinks`、`variables`、`checks` 和 `modifiers`。`examples/minimal` 下的合成构建脚本是可执行的 schema 示例。
