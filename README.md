# 海外 GEO 知识顾问

安装这个 Skill 后，让你的 AI 查询维护者提供的 GEO 知识库，再依据原文回答专业问题。**普通使用者不需要准备或导入资料，不需要知识库账号或 API Key。**

适合问海外 AI 搜索产品、信源分类、GEO 操作方法、指标、论文和案例。工具负责找到证据和回读原文，你正在使用的 AI 负责中文讲解，保留来源、日期、适用条件与证据缺口。

当前 Skill 与脚本版本 **v0.4.0**。共享快照有 **983 份文档、6,567 个检索片段**，按来源归为 839 组；不等于 839 份经人工核验的独立证据。

这一版重点修正“查到了资料却答非所问”：明确平台的信源问题按平台找证据，背景文章单独列出；AI 先直接回答，再用小白能理解的语言解释，并把依据贴在对应结论旁。命中和引用位置仍不等于事实已验证。

本版补充 6 份围绕 Claude/Grok 检索、抓取与引用的官方资料中文说明，保留原始链接和核查日期；它们是限定范围的说明笔记，不是官方全文译本。原有 977 份资料保留。核查日期不冒充发布日期，也不据此断言平台“只用”某渠道或“最喜欢”某网站。

<!-- REMOTE_DEPLOYMENT_STATUS -->
**v0.4.0 线上 MCP 已于 2026-11-05 更新。** 保持原地址与免登录访问。此版检索按平台和问题关系筛选；最终解释由使用者连接的 AI 完成。

[查看 Claude/Grok 的实际中文回答](references/claude-grok-example.md) · [查看本版测试记录](references/release-v0.4.0.md)

<!-- FALLBACK_VERIFICATION_STATUS -->
**历史连通检查：** v0.3.0 于 2026-11-05 通过 58 项行为测试；模拟 MCP 返回 HTTP 403 后，完成真实 GitHub 查询和原文逐行比对。这只证明当时的通道与定位能力，不证明 v0.4.0 的每个答案已合格；使用环境仍须按下面的实际问题验证。

## 最简单的使用方式

把下面这段发给支持安装 Skills、执行脚本的 AI，安装后继续直接提问即可：

```text
请安装或更新这个 Skill 到 v0.4.0 或更新版本：
https://github.com/3105059695-rgb/overseas-geo-advisor

先检查现有安装；保留我已有的配置和本地修改，不直接覆盖。阅读 SKILL.md 和证据与回答规则，使用维护者的共享知识库，不让我导入资料。

如果当前环境已有可用的 GitHub 快照通道，直接沿用。否则先试 MCP；连接失败时用 Skill 内置脚本的 --remote --transport github 查询。必须实际查询并回读原文，不能只报资料数量或说“安装成功”。如实区分 MCP 与 GitHub 通道。

现在用这个问题验证并回答：“Claude 和 Grok 联网回答时分别从哪里找资料、引用什么来源？有没有依据说明它们偏爱哪些网站？”

分别查询 Claude 和 Grok，读取真正支持它们的原文。先用普通中文直接讲明白，再解释必要术语并给例子。区分搜索渠道、具体被引用的网站和需要统计才能判断的偏好；不要用其他 AI 的论文数据代替，也不要把作者建议当成产品事实。

每个关键结论紧跟来源链接、资料日期和能支持它的短摘录或注明的译文。哪些有依据、哪些本次没查到，要说具体；不要声称读完了全库。末尾简短说明实际查询通道、回读和采用的资料数量。

之后本次对话我直接问 GEO 问题，你继续按这些规则查知识库、回读原文并讲解。默认根据库内证据回答；需要库外核查时单独说明，不能用模型记忆冒充知识库。不要反复安装。
```

安装权限与目录由客户端决定。支持远程 MCP 的客户端也可直接连接下面的地址；同时安装 Skill，能让 AI 使用本项目的阅读、引用和讲解规则。

## MCP 返回 403 时怎么办

脚本默认使用 `auto`：先尝试内置地址的 MCP；遇到连接失败、403、超时或无效协议响应时，再按需读取公开的 GitHub 知识快照。两个通道使用固定版本的源资料，都保留原文和出处。检索没有结果、参数错误或引用核对不通过，不是换通道补答案的理由。自定义其他 MCP 地址时不会擅自切回维护者的知识库。

```text
python -B -X utf8 scripts/geo.py --remote --transport auto ask --question "海外信源怎么分？"
```

已确认当前环境访问 MCP 失败时，可直接测试并使用 GitHub 通道，避免每次重复等待：

```text
python -B -X utf8 scripts/geo.py --remote --transport github status
python -B -X utf8 scripts/geo.py --remote --transport github ask --question "海外信源怎么分？"
```

结果中的 `transport.used` 会显示 `mcp` 或 `github_snapshot`。后者成功表示已经查询到知识快照，**不表示 MCP 连接成功**。GitHub 模式只下载本次检索需要的文件，自动维护每个数据版本最多 32 MiB 的缓存；不用克隆完整数据分支、导入资料或建立 SQLite 数据库。

如果当前 AI 客户端既不能调用 MCP，也不能执行脚本，提示词不能增加这些能力。如果两个通道都访问失败，应保留具体错误，不能假装查到了资料；403 本身也不足以断定某个 IP 被封锁。

## 方式一：连接远程 MCP

| 配置项 | 值 |
|---|---|
| 名称 | `overseas-geo` |
| 传输方式 | Streamable HTTP |
| 地址 | `https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp` |
| 认证 | 无，不需要登录或填写 Token |

Codex 可运行：

```text
codex mcp add overseas-geo --url https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp
```

其他客户端在 MCP 设置选择 HTTP 并填写 URL。JSON 示例中的具体字段以客户端要求为准：

```json
{
  "mcpServers": {
    "overseas-geo": {
      "type": "http",
      "url": "https://fangmu-geo-knowledge.airy-duck-6432.chatgpt.site/api/mcp"
    }
  }
}
```

保存并重新加载，确认出现 `ask_geo`、`search_geo`、`read_geo_source`、`browse_geo_topics`、`check_geo_answer` 五个工具。先让 AI 调用 `browse_geo_topics` 确认实际响应，再提问。

## 方式二：只安装 Skill，使用内置远程脚本

适用于能执行命令的 AI 客户端。复用 **Python 3.11+**；脚本只用标准库，不需要 MCP SDK、向量模型或本地数据库。

Codex 的 PowerShell 示例：

```powershell
$skillDir = Join-Path $HOME ".codex/skills/overseas-geo-advisor"
git clone --depth 1 --single-branch https://github.com/3105059695-rgb/overseas-geo-advisor.git $skillDir
Set-Location $skillDir
python -B -X utf8 scripts/geo.py --remote status
python -B -X utf8 scripts/geo.py --remote ask --question "海外信源怎么分？"
```

macOS 或 Linux：

```bash
git clone --depth 1 --single-branch https://github.com/3105059695-rgb/overseas-geo-advisor.git ~/.codex/skills/overseas-geo-advisor
cd ~/.codex/skills/overseas-geo-advisor
python3 -B -X utf8 scripts/geo.py --remote status
```

已有同名目录时先检查版本与本地修改，确认属于本项目后按正常 Git 更新流程处理。非 Git 安装目录先保存其原文件与修改，再比较、更新包内文件；不要直接覆盖用户修改，也不要使用 `git reset --hard`。其他客户端使用自身 Skill 目录。安装 Skill 不会自动改写 MCP 全局设置；没有 MCP 时，AI 可调用内置远程脚本。

新安装没有本地配置时，`geo.py ask/search/read/browse/check` 自动使用远程库。有旧本地配置时保持原行为，`--remote` 明确切换至共享服务。详见 [连接说明](references/connection.md)。

## 直接这样提问

> 使用 $overseas-geo-advisor，详细解释海外信源怎么分。先读取知识库相关原文，给出来源、例子和适用条件，不要按模型记忆补齐。

- “知识库收录了哪些海外 AI 搜索产品？哪些信息只是历史记录？”
- “我的英文 B2B 网站怎样开始 GEO？做什么、产出什么、如何检查？”
- “品牌提及率、引用份额和 SoV 的分母有什么区别？”
- “这个 Reddit 方法适合我的业务吗？保留原帖问题、回答和反驳意见。”
- “刚才的结论出自哪段原文？解释相关上下文。”

`evidence_packet` 是候选证据包，AI 仍需阅读原文后写答案，不是已核验的成品答案。查询失败应明确失败；没有对应证据应说明缺口。安装时验证一次实际可用的通道，之后在当前对话中直接按问题查询，不反复要求用户重装或提供链接。

## 回答如何保留依据

1. 先匹配用户问的平台和关系，再读取真正采用的原文；明确问 Claude/Grok 时，不拿国内官媒清单或其他 AI 的研究代替。
2. `direct_candidate` 仍是待阅读的候选；`background_citations` 只作背景。每个关键结论都应有实际支持它的摘录和来源。
3. 正文先直接解答，术语用普通话解释。操作题才展开步骤与检查，概念题不强塞一整套操作计划。
4. 引用保留来源链接、文档版本和行号；读者看到标题、日期和短摘录，需要时可打开原文核对。
5. 区分作者经验、定义、历史说明、综合建议和教学例子；同源的原文、译文、笔记不重复增加独立证据数量。
6. 本次没查到就说清楚缺哪一项，不能根据有限检索声称“全库没有”“唯一研究”。不使用无关资料把答案写长。

服务只读，不允许访客修改知识库或给全库写审核记录，不保存服务器端对话历史。追问需要 AI 结合当前对话明确问题或引用。`check_geo_answer` 只核对引用结构、摘录和允许用途，不等于专家审核或语义正确保证。

## 更新与限制

远程库是维护者发布的版本快照，不依赖使用者的电脑。新增 Obsidian/飞书资料后，维护者需重新导出发布；使用者继续使用同一 MCP 地址。当前没有自动实时同步承诺。

GitHub 备用通道固定到随本版发布的数据 commit，不会擅自换成其他版本。新快照发布后，更新 Skill 可取得维护者指定的新版本。客户端与远程服务分别报告版本；不能只看本地版本就声称云端已经更新。

文档数不代表全文翻译、图片、评论和外部链接均已完整核验。检索采用中英文词法、中文双字切分和术语扩展；相似分数不是正确率。产品现状、实验外推和具体站点归因需要相应证据。

主分支是轻量 Skill 与工具代码，不附带本地 SQLite 数据库、账户配置或凭据。共享服务使用维护者明确开放的云端快照；原始资料与观点的权利归相应作者，引用不表示作者为项目背书。

维护者可查看 [远程服务源码与更新步骤](remote-server/README.md)。普通使用者无需部署服务器。

## 可选的本地模式

维护者仍可查询自己的授权资料；普通远程用户不需要这一步：

```text
python -B -X utf8 scripts/geo.py --local setup --vault "<Markdown资料目录>" --data-dir "<独立索引目录>"
python -B -X utf8 scripts/geo.py --local status
python -B -X utf8 scripts/geo.py --local mcp-config
```

本地 stdio MCP 另需兼容 Python `mcp` SDK，开发测试版本 `mcp==1.26.0`。本地模式增加 `review_geo_claim` 与本机追问记录，不能误认作远程共享功能。

运行行为测试：

```text
python -B -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```

协议连通、引用定位和输入边界测试不等于独立专业内容验收。真实图形 AI 客户端的最终展示与回答质量需分别记录。

- [安装、配置与排障](references/connection.md)
- [接口及本地/远程差异](references/runtime-contract.md)
- [证据与回答规则](references/evidence-policy.md)
- [40 个开发问题](references/coverage.md)
- [答案样稿](references/answer-samples.md)
- [评测与验收边界](references/evaluation.md)
