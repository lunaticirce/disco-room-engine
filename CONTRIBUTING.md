# 贡献指引

欢迎为引擎、测试、文档和原创示例贡献代码。

## 内容边界

请勿提交提取出的游戏数据库、受版权保护的对白、美术、音频、玩家存档、私人手记或凭据。回归测试用的 fixture 必须使用为本仓库创作的原创合成内容。

## 开发

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples
git diff --check
```

改动请保持聚焦。新增条件谓词或用户脚本动词时，应附带一个小的合成回归测试，用以说明其状态语义。
