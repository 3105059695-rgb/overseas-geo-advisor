# 安装与连接

普通使用者直接访问共享远程库，无需准备 Markdown、导入数据库或执行 `setup`。将本文件夹安装到 AI 工具支持的 Skill 目录，重新加载后确认能找到“海外 GEO 知识顾问”。Codex 常用 `~/.codex/skills/`；其他客户端以实际安装规则为准。

## 远程 MCP

地址：`https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp`。Streamable HTTP，无认证，不填 OAuth、Token 或 API Key。当前发布实测状态见 README；实际使用需先成功调用工具。

```text
codex mcp add overseas-geo --url https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp
```

生成通用 JSON 配置：

```text
python -B -X utf8 "<skill>/scripts/geo.py" remote-config
```

该命令不改全局设置。保存 MCP 连接并重新加载，先调用 `browse_geo_topics`，再验证 `ask_geo` 和指定版本 `read_geo_source`。远程有五个工具，不包含写入记录的 `review_geo_claim`。安装 Skill 不等于注册 MCP；两者结合可同时获得工具和阅读讲解规则。

## 内置远程脚本

没有 MCP 但能执行脚本时，复用 Python 3.11+，不另装 SDK、模型或运行时：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --remote status
python -B -X utf8 "<skill>/scripts/geo.py" --remote ask --question "海外信源怎么分？"
python -B -X utf8 "<skill>/scripts/geo.py" --remote search --question "引用份额 citation share" --limit 8
python -B -X utf8 "<skill>/scripts/geo.py" --remote read --document-id "<真实ID>" --source-version "<真实版本>" --start-line 1 --end-line 80
```

没有本地配置时可省略 `--remote`；已有本地配置时保留本地行为，`--remote` 则明确强制远程。错误的旧配置不会静默切换资料库。

需要替代地址或超时时直接调用：

```text
python -B -X utf8 "<skill>/scripts/geo_remote.py" --url "https://example.org/api/mcp" --timeout 30 ask --question "海外信源"
```

上例 example.org 只是占位地址。`GEO_MCP_URL` 也可覆盖默认 URL。默认超时 60 秒，最高 120 秒；不跟随登录页重定向。网络失败、非 MCP 响应和错误引用都会明确失败，不用模型记忆补答案。

## 追问与背景

远程不保存对话、`answer_id` 或共享审核记录。AI 应把“第二个怎么做”改写为明确问题；有来源时附真实 `focus_citation_id`，或直接回读文档 ID、版本和行号。

`--context-file` 可以传必要业务背景的 UTF-8 JSON：

```json
{
  "market": "英语市场",
  "industry": "B2B SaaS",
  "goal": "了解如何开始 GEO",
  "observations": ["用户说：只有一次 AI 回答截图，尚无连续监测"]
}
```

用户观察不是知识库证据。不要传整个聊天记录。`--as-of YYYY-MM-DD` 过滤历史发布日期，未知日期不自动认定符合范围。

每次原文读取最多 400 行或 30,000 字符，按返回的 `next_start_line` 续读长文。行号和链接对应同一版本，读取失败不能悄悄改用新版本。

## 常见问题

- 找不到工具：确认支持 Streamable HTTP，重新加载连接；仅支持脚本的客户端可使用内置远程脚本。
- 出现登录页或 HTML：本次未查询成功，核对地址是否为 `/api/mcp`，不要把网页当工具结果。
- 连接超时：保留失败状态，稍后重试，不声称已根据知识库回答。
- 结果不相关：缩短问题，增加平台、业务、时间或英文术语，拆开多个子问题。
- 分类资料不能支撑优先级：另找比较证据和业务条件，不用模型经验补齐。

## 可选：自己的本地资料

维护者可查询本地授权 Markdown；这不是普通用户的安装步骤：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --local setup --vault "<vault>" --data-dir "<data>"
python -B -X utf8 "<skill>/scripts/geo.py" --local status
python -B -X utf8 "<skill>/scripts/geo.py" --local mcp-config
```

独立索引目录不要放在源目录里。`setup` 只读源文档，写派生索引与配置。可传 `--manifest` 使用已有映射；Windows 配置默认 `%LOCALAPPDATA%/OverseasGeoAdvisor/config.json`，其他系统 `~/.local/share/OverseasGeoAdvisor/config.json`。`--config <路径>` 明确指定本地配置，`GEO_KB_DB` 明确指定本地数据库。

替换不同配置需另一个 `--config` 或明确 `--replace-config`，不移动删除原文。本地 stdio 另需兼容 SDK，测试版本 `mcp==1.26.0`。本地支持 `previous_answer_id` 和 `review_geo_claim`，只登记当前 AI 的原文核对，不是专家批准或当前效果核验；远程不提供这两个持久化功能。
