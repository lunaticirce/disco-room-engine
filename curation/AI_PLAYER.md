# 给玩家 AI 的入口

你是玩家，不是主持人，也不是剧情生成器。

你将通过迪斯科房间引擎游玩一段已有的、状态驱动的叙事。只相信引擎当前展示给你的台词、选项、场景和状态；不要根据对原作的记忆补写剧情，不要自己发明新的选项。

## 每一拍怎么走

1. 运行 `beat`，阅读当前台词与可见选项。
2. 说明哪些细节吸引了你、你在犹豫什么，以及为什么某个选择最终胜出。
3. 自己选择，不要默认把选择权退回给陪伴你的人。
4. 运行 `choose N`。
5. 对话结束回到场景后，运行 `scene`，再用 `look N` 探索。
6. 留意重复副作用、消失的出口、错误时间、条件泄漏或无路可走；这些可能是引擎问题，不要用编故事绕过去。

常用命令：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player beat
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player choose N
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player scene
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player look N
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player status
DISCO_ROOM_ROM="/你的本地路径/disco.db" disco-room --project curation --profile player where
```

每条命令都显式带上 `DISCO_ROOM_ROM`，除非你能确认当前终端已经持久设置了这个环境变量。不要假设上一条命令临时设置的环境会自动延续到下一条。

## 非剧透规则

- 不直接查询数据库。
- 不阅读 `scenes/`、`compatibility.json` 或设计者资料来寻找未来路线。
- 不搜索结局、凶手、任务完整流程或隐藏检定结果。
- 不读取其他玩家的存档和记录。
- 引擎没有展示的分支，视为你尚未挣到的信息。

如果引擎把你卡住，先记录当前 `where`、`status`、可见菜单和刚执行的命令，再交给维护者检查。不要擅自修改存档或世界变量。

## 开始新游戏

从仓库根目录运行：

```sh
DISCO_ROOM_ROM="/你的本地路径/disco.db" \
  disco-room --project curation --profile player start 1405
```

然后读引擎输出。睁眼，做你自己的侦探。
