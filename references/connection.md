# 安装与连接

## 安装 Skill

把 `overseas-geo-advisor` 文件夹放到目标 AI 工具支持的 Skill 目录。Codex 常用 `~/.codex/skills/`。重新加载后确认能找到“海外 GEO 知识顾问”。不同产品的安装入口以该客户端为准。

Skill 包没有维护者的完整私人知识库。需要执行本地资料配置，或以后连接实际部署的授权服务。当前没有可供外部用户直接使用的远程 URL。

## 本地命令模式

要求 Python 3.11 或更新版本；检索脚本使用标准库 SQLite。复用已有 Python，不为本 Skill 建立新的 portable runtime。

下面用 `<skill>`、`<vault>`、`<data>` 表示本机实际绝对路径，在当前 shell 中正确加引号：

```text
python -B -X utf8 <skill>/scripts/geo.py setup --vault <vault> --data-dir <data>
python -B -X utf8 <skill>/scripts/geo.py status
python -B -X utf8 <skill>/scripts/geo.py ask --question "海外信源怎么分？"
python -B -X utf8 <skill>/scripts/geo.py search --question "引用率 mention rate" --limit 8
```

本项目已有资料映射时，setup 增加 `--manifest <obsidian-map-plan.json>`。其他资料库可以不传映射，由构建程序登记合法 Markdown。

`setup` 只读取原资料，写独立索引和本用户配置。Windows 默认配置位置是 `%LOCALAPPDATA%/OverseasGeoAdvisor/config.json`，其他系统为 `~/.local/share/OverseasGeoAdvisor/config.json`。可用全局参数 `--config` 指定另一配置文件；`GEO_KB_DB` 可直接指定已有数据库。

再次配置不同资料位置时需要显式新配置路径，或使用 `--replace-config`。该选项仅替换本工具配置，不移动、删除原文。索引更新使用 setup 或明确的 build 命令，原始历史版本仍保留。

## 追问与历史引用

```text
python -B -X utf8 <skill>/scripts/geo.py ask --question "刚才那篇原文怎么说？" --previous-answer-id <上次answer_id> --focus-citation-id <真实citation_id>
python -B -X utf8 <skill>/scripts/geo.py read --document-id <document_id> --source-version <source_version> --start-line 1 --end-line 80
```

`--context-file` 可以传只包含必要业务条件的 UTF-8 JSON。`--as-of YYYY-MM-DD` 用于明确历史时间；未知发布日期不能被自动认定符合日期范围。

遇到新资料，由回答的 AI 读取原文后可执行 `review --bundle-file <JSON路径>`，记录本次断言核对。内容包括 document_id、source_version、statement、exact_quote、allowed_use、conditions、review_note。仅允许 attributed_report、definition、historical；不能将这个命令用来批准确定的现行机制或效果。它写本地派生记录，原始文件保持只读。

## 本地 MCP 模式

MCP 服务另需 `mcp` Python SDK。本轮测试复用既有 `mcp==1.26.0`；不自动下载安装依赖。若目标环境没有该依赖，需要维护者自行安排安装，或继续使用标准库命令模式。

```text
python -B -X utf8 <skill>/scripts/geo.py mcp-config
```

这会生成带实际解释器、脚本与数据库路径的 JSON 配置，不改全局客户端设置。把配置用于支持本地 stdio MCP 的客户端；若它采用不同配置格式，按其规则填写相同 command/args。

服务器通过客户端启动的标准输入输出通信，不开启网络端口。它继承当前本地账户的访问范围；这不是远程多用户鉴权服务。

首次连通应验证 initialize、工具列表、一次 ask、指定版本 read、一次追问，以及错误引用或缺失资料的处理。SDK 连通测试和真实用户 AI 的最终答案测试分别记录。

## 外部用户的方式

用户可安装本 Skill 并使用自己的授权资料副本。若希望所有用户持续访问同一知识库，需要另外部署远程服务，落实真实地址、鉴权、资料开放范围、模型与运行费用，再做客户端试点。不能分发本机数据库路径代替在线连接。
