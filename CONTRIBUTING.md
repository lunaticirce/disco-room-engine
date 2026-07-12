# 贡献指引

欢迎为引擎、测试、文档、原创示例和手工策展层贡献内容。

## 内容边界

请勿提交提取出的游戏数据库、受版权保护的对白、美术、音频、玩家存档、记录墙、私人手记、研发 `notes` 或凭据。回归测试用的 fixture 必须使用为本仓库创作的原创合成内容。

策展贡献可以包含原创场景描述、菜单标签、路线、条件和功能性兼容映射。不要从数据库复制对白或把 ROM 调试记录写入公开场景。提交前运行 `python3 tools/curation.py audit curation`。

## 开发

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples tools
python3 tools/curation.py audit curation
git diff --check
```

改动请保持聚焦。新增条件谓词或用户脚本动词时，应附带一个小的合成回归测试，用以说明其状态语义。
