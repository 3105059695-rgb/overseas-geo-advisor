# 安装与使用：直接查询 GitHub 知识快照

本轮发布目标为 **v0.5.0**。普通用户安装 Skill 后直接提问，由 AI 查询维护者已经发布的资料；不注册知识库账号、不填 API Key、不导入资料、不运行 `setup`，默认不配置或调用 MCP。发布与实测结果以 README 的发布记录为准。

## 客户端需要什么

需要支持 Skill、脚本执行和 HTTPS 网络访问的 AI 客户端，以及现有 Python 3.11+。默认脚本只用标准库，不安装 MCP SDK、向量模型、SQLite 数据库或另一套运行时。纯聊天网页若没有这些能力，提示词不能替它增加安装入口或命令执行能力。

将本文件夹安装到客户端支持的 Skill 目录，重新加载后直接使用。Codex 常用 `~/.codex/skills/`；其他客户端以实际规则为准。已有安装先核对来源、版本和本地修改，保留修改后正常更新，不直接覆盖或强制重置。安装提示词见 [README](../README.md#最简单的使用方式)。

## 默认操作：AI 执行，用户只提问

1. AI 理解问题对象、关系、时间和所需答案形式，自行创建 `<分析.json>`，包含 `resolved_question`、`queries`、`keywords`；可选 `task`、`freshness`。
2. 无 `--config` 运行 `workflow prepare`，真正执行改写后的关键词多子查询，并按需回读公开快照里的对应版本原文。
3. AI 逐条判断证据。需要最新事实时使用客户端的网页工具打开原始来源，将本次联网补充单独记录；做不到就如实说明。
4. AI 自行创建判断文件、答案草稿，执行 `adjudicate` 与 `check`；检查失败就修正或缩小范围。
5. 交付对题、通俗的中文答案，保留来源、日期、样本与适用范围，说明具体缺口。

接口示例供执行 Skill 的 AI 使用，**不要求用户手填 JSON**：

```text
python -B -X utf8 "<skill>/scripts/geo.py" workflow prepare --question "GPT 更喜欢什么信源？" --analysis-file <分析.json> --output <证据包.json>
python -B -X utf8 "<skill>/scripts/geo.py" workflow adjudicate --packet <证据包.json> --judgments <语义判断.json> --output <采用范围.json>
python -B -X utf8 "<skill>/scripts/geo.py" workflow check --assessment <采用范围.json> --draft <答案草稿.json> --output <后置检查.json>
```

AI 分析最多形成 6 条子查询、20 个关键词；多平台问题分别覆盖。默认只有关键词多子查询，问题 embedding 与关键词 embedding 未启用，不能报告“三路都跑过”。AI 的问题理解和证据重排也不等于向量检索。字段与示例见 [完整工作流合同](workflow-v0.5.md)。

## 按需回读、版本与缓存

状态检查和补读来源可使用：

```text
python -B -X utf8 "<skill>/scripts/geo.py" status
python -B -X utf8 "<skill>/scripts/geo.py" read --document-id <真实ID> --source-version <真实版本> --start-line <起始行> --end-line <结束行>
```

ID、版本、行号必须来自本次真实检索。默认通过 HTTPS GET 按需读取公开 catalog、索引分片和所需原文，固定到随版本指定的数据 commit，并按清单校验文件与正文哈希。每个数据版本缓存上限 **32 MiB**；不克隆完整 `knowledge-snapshot` 分支、不下载整库或模型。

每次旧接口原文读取最多 400 行或 30,000 字符；有 `next_start_line` 时继续补读必要上下文。JSON 文件自身显示行号不是归档正文行号，应以返回的正文 `line_start`、`line_end` 为准。来源读取失败不能静默替换为新版本。

查询成功不等于原文已读，原文已读也不等于能支持某个结论。状态里的资料数量不是阅读证据。默认工作流以 `retrieval_trace` 报告真实查询、回读和可用路线，不能声称 MCP 已连接。

## 追问、日期与联网

AI 只在必要时用 `--context-file` 传相关前文，把“那 Claude 呢”改写成保留前文关系、更新平台的具体问题；用户观察需明确标记，不上传整个聊天记录。临时分析、判断与草稿由 AI 保存在本次任务的可写目录，不是用户知识库导入。

发布日期、观测时间、收录时间和核查时间分别保存。`--as-of YYYY-MM-DD` 约束历史范围；未知日期不自动认定符合范围。旧资料不能因为今天打开就变成最新事实。当前 AI 的联网补充要记录实际原始 URL、打开结果和核查日期，不能用搜索摘要或模型记忆冒充原文。

## 常见问题

- 客户端不能安装 Skill 或执行脚本：说明实际能力缺口；不要反复提示安装 MCP，也不要暗示普通网页已获得这些能力。
- GitHub 超时、403 或完整性校验失败：保留具体错误，不跳过校验、不擅自改数据版本或切换 MCP；未成功查询时不能给出伪称基于知识库的答案。
- 用户换 Wi-Fi 没作用：先确认脚本实际运行位置；AI 平台云端执行的网络出口通常不是用户本机。
- 结果偏题：检查 AI 分析中的平台与问题关系，按平台拆开、补充对应中英文术语再查；背景文章不能填补核心事实缺口。
- 找到来源却缺日期或实验条件：保留缺失状态，不拼接百分比，不把作者经验改成通用规则。
- 向量显示 `unavailable`：这是默认标准库模式的真实状态；不自动下载模型，不要求用户准备索引。
- 关键词没有结果：说明本次查询范围和缺口；必要时用客户端联网核查，单独标注库外来源，不声称“全库没有”。

## 保留的历史 MCP / 旧命令说明

下面是已有维护者可显式选择的兼容功能。本版默认安装和提问不配置、不调用 MCP，也不需要先试 MCP 失败再使用 GitHub。保留旧地址与文档不表示旧服务已更新为本轮工作流。

<details>
<summary>展开旧 MCP 连接与显式传输参数（非默认）</summary>

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

## 旧接口的显式传输选择

旧 ask/search/read 命令仍可使用。当前默认直接 GitHub；下面保留显式选择传输方式的用法：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --remote status
python -B -X utf8 "<skill>/scripts/geo.py" --remote ask --question "海外信源怎么分？"
python -B -X utf8 "<skill>/scripts/geo.py" --remote search --question "引用份额 citation share" --limit 8
python -B -X utf8 "<skill>/scripts/geo.py" --remote read --document-id "<真实ID>" --source-version "<真实版本>" --start-line 1 --end-line 80
```

访问自己的资料时明确选择 `--local`；默认问答使用 GitHub 公开快照，不会把旧维护者配置当作普通用户的资料来源。

脚本支持三种方式，参数放在 `status`、`ask` 等子命令之前：

| 参数 | 行为 |
|---|---|
| `--transport auto` | 显式选择旧自动模式；内置 MCP 地址连接失败时使用固定的 GitHub 公开快照；不会替换自定义资料服务 |
| `--transport mcp` | 只测 MCP，失败就返回失败，适合排查连接 |
| `--transport github` | 当前默认；跳过 MCP，直接检索同一版本的 GitHub 快照 |

豆包等环境若没有原生 MCP 注册入口，直接使用脚本。确认其 MCP 访问失败后，可以这样验证备用通道：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github status
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github ask --question "Claude 和 Grok 联网回答时分别从哪里找资料、引用什么来源？"
python -B -X utf8 "<skill>/scripts/geo.py" --remote --transport github read --document-id "<上一步真实ID>" --source-version "<上一步真实版本>" --start-line <真实起始行> --end-line <真实结束行>
```

以 `transport.used` 报告实际通道：`mcp` 为 MCP 查询，`github_snapshot` 为 GitHub 快照查询。备用通道可用不等于 MCP 已注册或已连接。验证应包含查询和原文回读，不只是查看仓库里的资料数量声明。

确认连接后还要检查是否对题：分别查看 Claude 与 Grok 的 `platform_coverage`，回读 `citations` 中与各平台对应的原文，`background_citations` 不充当产品事实。比较查询没覆盖某个平台时，单独检索该平台。最后给出一句直接回答并附真正支持它的原文和链接；不能把“有结果”当作“正确回答”。可直接使用 [README 中的安装与使用提示词](../README.md#最简单的使用方式)。

GitHub 模式通过 HTTPS GET 按需读取公开的 catalog、索引分片和所需原文；固定到本版的数据 commit，按完整性清单校验文件及正文版本。它不需要用户导入数据，不下载整个数据分支、不创建 SQLite，自动缓存最多 32 MiB。GitHub 也不可达时仍会如实失败。

需要替代地址或超时时直接调用：

```text
python -B -X utf8 "<skill>/scripts/geo_remote.py" --url "https://example.org/api/mcp" --timeout 30 ask --question "海外信源"
```

上例 example.org 只是占位地址。`GEO_MCP_URL` 也可覆盖默认 URL。自定义 URL 与内置地址不同时，`auto` 不会切换到维护者的资料；只有明确选择 `--transport github` 才使用维护者快照。

`auto` 对默认 MCP 的单次探测超时最多 12 秒，之后可尝试备用通道。显式 `mcp` 模式使用 `--timeout`，默认 60 秒、最高 120 秒。不把登录重定向或 HTML 拦截页当作 MCP 成功，也不把备用结果误认作指定 MCP 的结果。


</details>

## 可选：自己的本地资料

维护者可查询本地授权 Markdown；这不是普通用户的安装步骤：

```text
python -B -X utf8 "<skill>/scripts/geo.py" --local setup --vault "<vault>" --data-dir "<data>"
python -B -X utf8 "<skill>/scripts/geo.py" --local status
python -B -X utf8 "<skill>/scripts/geo.py" --local mcp-config
```

独立索引目录不要放在源目录里。`setup` 只读源文档，写派生索引与配置。可传 `--manifest` 使用已有映射；Windows 配置默认 `%LOCALAPPDATA%/OverseasGeoAdvisor/config.json`，其他系统 `~/.local/share/OverseasGeoAdvisor/config.json`。`--config <路径>` 明确指定本地配置，`GEO_KB_DB` 明确指定本地数据库。

替换不同配置需另一个 `--config` 或明确 `--replace-config`，不移动删除原文。本地 stdio 另需兼容 SDK，测试版本 `mcp==1.26.0`。本地支持 `previous_answer_id` 和 `review_geo_claim`，只登记当前 AI 的原文核对，不是专家批准或当前效果核验；远程不提供这两个持久化功能。
