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

## 内置远程脚本与备用通道

没有 MCP 但能执行脚本时，复用 Python 3.11+，不另装 SDK、模型或运行时：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --remote status
python -B -X utf8 "<skill>/scripts/geo.py" --remote ask --question "海外信源怎么分？"
python -B -X utf8 "<skill>/scripts/geo.py" --remote search --question "引用份额 citation share" --limit 8
python -B -X utf8 "<skill>/scripts/geo.py" --remote read --document-id "<真实ID>" --source-version "<真实版本>" --start-line 1 --end-line 80
```

没有本地配置时可省略 `--remote`；已有本地配置时保留本地行为，`--remote` 则明确强制远程。错误的旧配置不会静默切换资料库。

脚本支持三种方式，参数放在 `status`、`ask` 等子命令之前：

| 参数 | 行为 |
|---|---|
| `--transport auto` | 默认；内置 MCP 地址连接失败时使用固定的 GitHub 公开快照；不会替换自定义资料服务 |
| `--transport mcp` | 只测 MCP，失败就返回失败，适合排查连接 |
| `--transport github` | 跳过 MCP，直接检索同一版本的 GitHub 快照 |

豆包等环境若没有原生 MCP 注册入口，直接使用脚本。确认其 MCP 访问失败后，可以这样验证备用通道：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github status
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github ask --question "Claude 和 Grok 联网回答时分别从哪里找资料、引用什么来源？"
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github read --document-id "<上一步真实ID>" --source-version "<上一步真实版本>" --start-line <真实起始行> --end-line <真实结束行>
```

以 `transport.used` 报告实际通道：`mcp` 为 MCP 查询，`github_snapshot` 为 GitHub 快照查询。备用通道可用不等于 MCP 已注册或已连接。验证应包含查询和原文回读，不只是查看仓库里的资料数量声明。

确认连接后还要检查是否对题：分别查看 Claude 与 Grok 的 `platform_coverage`，回读 `citations` 中与各平台对应的原文，`background_citations` 不充当产品事实。比较查询没覆盖某个平台时，单独检索该平台。最后给出一句直接回答并附真正支持它的原文和链接；不能把“有结果”当作“正确回答”。可直接使用 [README 中的安装与使用提示词](../README.md#最简单的使用方式)。

备用模式通过 HTTPS GET 按需读取公开的 catalog、索引分片和所需原文；固定到本版的数据 commit，按完整性清单校验文件及正文版本。它不需要用户导入数据，不下载整个数据分支、不创建 SQLite，自动缓存最多 32 MiB。GitHub 也不可达时仍会如实失败。

需要替代地址或超时时直接调用：

```text
python -B -X utf8 "<skill>/scripts/geo_remote.py" --url "https://example.org/api/mcp" --timeout 30 ask --question "海外信源"
```

上例 example.org 只是占位地址。`GEO_MCP_URL` 也可覆盖默认 URL。自定义 URL 与内置地址不同时，`auto` 不会切换到维护者的资料；只有明确选择 `--transport github` 才使用维护者快照。

`auto` 对默认 MCP 的单次探测超时最多 12 秒，之后可尝试备用通道。显式 `mcp` 模式使用 `--timeout`，默认 60 秒、最高 120 秒。不把登录重定向或 HTML 拦截页当作 MCP 成功，也不把备用结果误认作指定 MCP 的结果。

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

- 找不到工具：确认支持 Streamable HTTP，重新加载连接；客户端没有原生 MCP 入口时使用内置脚本，不重复尝试不存在的注册命令。
- MCP 返回 403、登录页或 HTML：核对完整地址是否为 `/api/mcp`，再用 `--transport github` 实测。不要把网页当工具结果，也不要仅凭 403 断定 IP 被封锁。
- MCP 超时：默认 `auto` 尝试备用通道；已确认不可达时直接使用 `github`，避免每次重复等待。两个通道都失败时保留错误，不声称已根据知识库回答。
- 让用户换 Wi-Fi：若代码运行在 AI 平台云端，用户本地 Wi-Fi 通常不会改变该执行环境的出口；先检查实际通道，而非要求用户反复换网络。
- GitHub 查询可用：沿用该通道继续提问、读取和核对，不要求用户安装数据库，不宣称 MCP 已连通。
- 结果不相关：确认本地 Skill 与工具返回版本；核对 `query_intent` 是否理解用户原问题，按平台拆开并补充对应英文术语。不能用背景候选或其他平台数据填满答案；有限检索无直接证据就明确本次缺口。
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
