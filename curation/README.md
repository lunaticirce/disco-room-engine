# 策展层

> 非官方、非商业、由爱好驱动的二创扩展补丁与策展引擎。

这里是迪斯科房间引擎的手工策展层。它把原始对话图重新组织成玩家能够行走的房间、地点、交互点和出口，让 AI 通过条件与状态逐步探索，而不是直接浏览整棵对话树。

本目录面向用户自行提供的《极乐迪斯科》兼容 SQLite 数据库。它不是官方内容包，与 ZA/UM 或《极乐迪斯科》的权利人没有隶属或背书关系。

## 包含什么

- `scenes/`：原创中文空间描述、菜单标签、路线连接与条件映射。
- `compatibility.json`：引擎与兼容数据库之间必要的功能性修补。
- `profiles/player.json`：可直接运行的匿名玩家档案。
- [`AI_PLAYER.md`](AI_PLAYER.md)：交给玩家 AI 的非剧透行动契约。
- `wall/`：可复制的记录墙骨架（含 `README.md` 记法契约 + 编年 / 人物 / 线索 / 场景 各类页模板）。

这里不包含游戏数据库、提取对白、美术、音频、真实玩家存档、已填写的玩家记录墙或内部研发笔记。

## 开始

先在仓库根目录安装引擎：

```sh
python3 -m pip install -e .
```

然后提供一份你有权使用的兼容数据库，并从开场梦境开始：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player start 1405
```

嫌每条命令都带 `DISCO_ROOM_ROM=...` 太长，可以先设一次：`export DISCO_ROOM_ROM="/你的本地路径/disco.db"`，之后本终端里的命令就不必再带前缀。

之后可以继续：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player beat

DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player choose 1
```

第一次启动会在 `curation/data/` 下创建独立存档；该目录不会被 Git 跟踪。

## 为另一个 AI 建档

复制 `profiles/player.json`，修改文件名、`id`、`name`、`save`、四项属性与招牌技能。新档案文件及其存档默认都不会被 Git 跟踪，因此不同 AI 不会互相覆盖。

四项属性（`Intellect` / `Psyche` / `Physique` / `Motorics`）决定 24 项技能的起点，推荐总和约 **12**。几个起手形状可参考：

- **Thinker** — Intellect 5 / Psyche 3 / Physique 2 / Motorics 2
- **Sensitive** — Intellect 3 / Psyche 5 / Physique 2 / Motorics 2
- **Sorry Cop With A Spine** — Intellect 4 / Psyche 4 / Physique 2 / Motorics 2
- **Physical Disaster** — Intellect 2 / Psyche 3 / Physique 5 / Motorics 2

`signature_skill` 是侦探最初的那个声音，开新档时 +1——比如 `Inland Empire`（梦的逻辑、征兆）、`Volition`（克制、不自欺）、`Encyclopedia`（事实比身份先回来）。

正式开局前，可以先看侦探卡：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player card
```

## 血量、时间与休息

- 侦探有 **生命** 与 **士气** 两个池：检定失败或某些选择会扣，休息会回。
- **归零不是终局**——某个池到 0 会先触发一段崩溃，然后回满，你不会被永久卡死。
- 世界时钟随对话推进；`status` 能看当前是第几天、几点。
- 正常游玩不必管时间；需要手动调试时用 `time` 命令（开发者向）。

机制细节见 [`../docs/vitality.md`](../docs/vitality.md) 与 [`../docs/clock.md`](../docs/clock.md)。

## 记录墙

`wall/` 是一份**内容空白的记录墙骨架**（索引 `Home.md` + `README.md` 记法契约 + 编年 / 人物 / 线索 / 场景 各类的页模板）。它**自包含**——记法契约随包一起复制，复制后链接不断。它不是引擎的一部分，也不绑 profile；复制进你自己的目录，边玩边填，让这个侦探的经历长成一张属于自己的网。

```sh
cp -r curation/wall /你的墙目录
```

## 内容与许可边界

策展层中的原创文字、选择和编排按 `CC BY-NC-SA 4.0` 提供。该许可只覆盖本项目有权许可的原创贡献，不覆盖《极乐迪斯科》的名称、人物、世界观、数据库字段或其他第三方权利。

完整边界见 [`NOTICE.md`](NOTICE.md) 与仓库根目录的 [`LICENSING.md`](../LICENSING.md)。
