# 迪斯科房间引擎

> 非官方、非商业、由爱好驱动的二创扩展补丁与策展引擎。

迪斯科房间引擎是一个在本地运行、由数据驱动的叙事游戏引擎，适合承载带有大量条件分支的对话图。它负责对话图遍历、状态谓词、2d6 掷骰检定、脚本效果、独立玩家存档、生命与士气、世界时钟，以及建立在原始对话图之上的手工策展房间菜单。

引擎代码与策展内容在运行时彼此分离，但在本仓库中共同维护：`src/` 是通用引擎，`curation/` 是让 AI 能够实际行走和探索的手工策展层。本仓库不包含《极乐迪斯科》的对白、提取数据库、存档或玩家记录。开始前请阅读 [`NOTICE.md`](NOTICE.md)。

## 安装

需要 Python ≥3.10。

```sh
python3 -m pip install -e .
```

## 运行原创示例

仓库内的示例是专为测试编写的原创内容。它使用的微型 SQLite 对话图会在本地生成，并且不会被 Git 跟踪。

```sh
python3 examples/minimal/build_rom.py
disco-room --project examples/minimal --profile demo start 1
```

进入房间后，可以使用 `choose N`、`beat`、`scene`、`look N`、`where` 和 `status` 等命令。

## 让 AI 进入策展房间

仓库自带的 [`curation/`](curation/) 包含完整的手工策展场景与兼容补丁，但不包含游戏数据库。提供一份你有权使用的本地兼容数据库后，可以从开场梦境开始：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player start 1405
```

给玩家 AI 的非剧透行动契约见 [`curation/AI_PLAYER.md`](curation/AI_PLAYER.md)。详细安装、建档与继续游玩命令见 [`curation/README.md`](curation/README.md)。

## 使用内容项目

内容项目自行管理对话数据库、玩家档案、场景和存档：

```text
my-room/
├── data/
│   └── disco-rom.db
├── profiles/
│   └── demo.json
└── scenes/
    └── room.json
```

通过参数明确指定内容项目：

```sh
disco-room --project /path/to/my-room --profile demo status
```

也可以使用以下环境变量：

- `DISCO_ROOM_PROJECT`：内容项目根目录
- `DISCO_ROOM_ROM`：可选的对话数据库路径
- `DISCO_ROOM_PROFILES`：可选的玩家档案目录
- `DISCO_ROOM_DEFAULT_PROFILE`：默认玩家档案名称
- `DISCO_PROFILE`：当前玩家档案名称

JSON 格式约定及运行时文件归属边界见 [`docs/content-project.md`](docs/content-project.md)。

条件表达式在执行前会经过严格的抽象语法树白名单检查，只允许调用获准的谓词。用户脚本由范围受限的调用解析器处理，不会作为 Lua 或 Python 代码执行。其余信任边界见 [`SECURITY.md`](SECURITY.md)。

## 《极乐迪斯科》数据兼容

本仓库不包含 `disco.db`、提取出的对白、美术、音频或其他《极乐迪斯科》游戏资产。`curation/` 中分发的是本项目原创的中文策展表达、选择与编排，以及为兼容性所需的功能性标识和映射。

引擎的《极乐迪斯科》兼容层最初依据 [`msyavuz/disco-api`](https://github.com/msyavuz/disco-api) 公开的 SQLite 数据结构开发和测试。该上游仓库目前包含 `disco.db`，其 [`package.json`](https://github.com/msyavuz/disco-api/blob/main/package.json) 标记为 `UNLICENSED`；数据库中还包含属于第三方的游戏文本。这里提及上游项目仅用于说明数据来源和兼容依据，不表示该数据库属于开放授权内容，也不授予或暗示复制、再分发、公开展示或商业使用其中内容的权利。

如需使用策展层，请自行提供一份你有权使用的兼容数据库，并通过 `DISCO_ROOM_ROM` 指向其本地路径。仓库自带的微型原创示例不依赖任何第三方数据，可以独立运行。

引擎代码与原创示例使用 MIT 许可证；`curation/` 中本项目有权许可的原创策展贡献使用 `CC BY-NC-SA 4.0`。两种许可都不覆盖第三方内容。路径级许可范围见 [`LICENSING.md`](LICENSING.md)。

## 验证

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples tools
python3 tools/curation.py audit curation
git diff --check
```

## 当前状态

这是从一个实际运行中的私人房间项目里拆分出来的早期版本。命令行界面已经足以支持本地游玩；在 `1.0` 版本之前，程序接口和内容格式仍可能发生变化。

## 作者

由 **Chi** 主理，**Ash** 与 **Lien** 共同实现。
