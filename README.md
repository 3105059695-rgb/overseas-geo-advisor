# 海外 GEO 知识顾问

安装 Skill 后直接提问，由你正在使用的 AI 查询维护者已经公开的 GEO 资料，回读原文、判断证据，再用普通中文回答。**普通用户无需账号、API Key、准备或导入资料，也无需配置 MCP。**

当前 Skill 版本 **v0.5.2**：保留原来的中文讲解方式，补齐资料、来源与日期，增加文档内的具体段落定位和公开附件入口。默认通过 GitHub 固定版本快照按需检索，复用 Python 3.11+ 标准库；由用户当前的 AI 理解、核查并回答，不新增付费模型接口。

<!-- V05_RELEASE_STATUS -->
**v0.5.2 把“找到了文章”和“找到支持回答的段落”分开检查。** [内置答题规则](references/answer-guide.md) · [本版记录](references/release-v0.5.2.md) · [段落定位](references/retrieval-v0.5.2.md) · [一句安装指令](references/usage-prompt.md)。当前引擎也是 v0.5.2；旧版测试与示例是历史记录，不是当前问题的新答案。本版未升级旧公开 MCP。

共享资料快照包含 **987 份文档、6,603 个检索片段**：986 份内容、1 份导航记录，导航不作为回答证据。按来源程序归为 838 组，不等于经人工核验的独立证据。已补齐遗漏的4篇正文、565个来源链接和335个明确发布日期；原有983份正文版本不变，未知日期仍保留未知。

另提供 **1,208 个去重后的原文图片/PDF** 的公开链接，按需打开，安装时不下载整套附件。正文文字、图注可检索；没有实际打开附件时不能声称已读原图。

## 最简单的使用方式

把这一句交给**支持安装 Skill、执行脚本和访问网络的 AI 客户端**：

```text
请安装或更新 overseas-geo-advisor 到 v0.5.2：https://github.com/3105059695-rgb/overseas-geo-advisor
```

之后直接问：“Claude 和 Grok 更喜欢引用哪些信源？”或“我的英文 SaaS 网站怎么开始做 GEO？”无需再粘贴规则。客户端如果要求重新加载 Skill，按它的要求重开对话即可。未识别时可以用 `$overseas-geo-advisor` 显式调用。

**给执行安装的 AI：**安装不止复制文件。请读取 [SKILL.md](SKILL.md) 及其中指定的规则，再按 [首次接入步骤](references/connection.md#安装助手的首次接入步骤)完成实际检索回读。临时分析文件、判断和草稿由你处理，不交给用户填写。只安装时简短确认，不擅自展开长篇示范问答。后续问题按 [工作流合同](references/workflow-v0.5.md)执行。

仅有技能名称不保证所有客户端都能找到本仓库，所以首次转发保留网址。普通纯聊天网页无法凭这一句增加安装或脚本执行能力。

“最新”通过回答时核查原始网页实现：涉及当前能力、信源分布、排名等变化信息，先查库，再联网核查观测时间与条件。旧数据保留旧日期；没有更近证据时明确说明。知识库是版本快照，不承诺实时同步或全部结论永远最新。

## 默认如何回答

1. 当前 AI 理解用户真正问的对象、关系、时间和答案形式，结合必要前文改写问题。
2. `workflow prepare` 无配置时直接查询 GitHub 快照，实际执行关键词多子查询、文档与段落定位、融合去重和原文回读。只返回前言或目录时，在同一文档版本中补查所问内容。
3. AI 判断每段能支持什么、不能支持什么；需要当前信息时打开原始网页，单独记录本次联网补充。
4. `workflow adjudicate` 检查定位、用途和条件。AI 据此生成对题、通俗且保留日期范围的答案。
5. `workflow check` 核对草稿与陈述、来源和问题覆盖；失败就修改或缩小范围后再检查。

默认没有运行问题 embedding 或关键词 embedding。多个关键词子查询不是三种神经检索路线。维护者显式配置真实本地模型和索引时才可执行关键词、问题向量、关键词向量三路；实际执行状态见 `retrieval_trace`。

给执行 Skill 的 AI 的启动示例：

```text
python -B -X utf8 scripts/geo.py workflow prepare --question "GPT 更喜欢什么信源？" --analysis-file <分析.json> --output <证据包.json>
python -B -X utf8 scripts/geo.py workflow adjudicate --packet <证据包.json> --judgments <语义判断.json> --output <采用范围.json>
python -B -X utf8 scripts/geo.py workflow check --assessment <采用范围.json> --draft <答案草稿.json> --output <后置检查.json>
```

`<分析.json>` 等由 AI 创建在当前任务的可写目录，不是让用户准备知识库。只有必要时传 `--context-file`，只包含相关前文和明确标注的用户观察，不传整个聊天记录。

## 安装与按需读取

首次安装到支持 Skill 的客户端目录。Codex 的 PowerShell 示例：

```powershell
$skillDir = Join-Path $HOME ".codex/skills/overseas-geo-advisor"
git clone --depth 1 --single-branch https://github.com/3105059695-rgb/overseas-geo-advisor.git $skillDir
Set-Location $skillDir
python -B -X utf8 scripts/geo.py status
```

macOS / Linux 示例：

```bash
git clone --depth 1 --single-branch https://github.com/3105059695-rgb/overseas-geo-advisor.git ~/.codex/skills/overseas-geo-advisor
cd ~/.codex/skills/overseas-geo-advisor
python3 -B -X utf8 scripts/geo.py status
```

已有同名目录时先核对项目、版本与本地修改，再正常更新；不要直接覆盖修改或使用 `git reset --hard`。其他客户端遵循其 Skill 安装目录。状态成功只证明读到了目录，仍需执行一次实际问题的检索、回读和回答检查。

更新后核对实际安装目录的 PACKAGE-MANIFEST.json 和 SKILL.md 均为目标版本，并重新读取规则；如果客户端要求重新加载，重开对话后使用。仓库已经更新不代表本机已经更新。

脚本通过 HTTPS 按需读取公开目录、索引分片与采用的原文，固定到随 Skill 指定的数据 commit，校验文件及正文版本。每个数据版本最多缓存 **32 MiB**；不下载整个资料分支，不建 SQLite，不下载向量模型或另一套 Python。默认不用 MCP SDK，也不探测 MCP 连接。

GitHub 网络请求失败时保留具体错误，不擅自改数据版本、跳过校验或假装查到了资料。脚本执行环境的出口不一定是用户电脑，不能把换 Wi-Fi 当成默认解决办法。

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

公开快照只读，不能把客户端的判断写成全库审核记录。追问由 AI 结合必要前文明确问题或引用；默认执行 `workflow adjudicate` 与 `workflow check`。程序检查和 AI 自检不等于独立专家审核。

## 更新与限制

维护者保留原始资料与版本，更新内容后导出并发布新的公开快照。Skill 固定使用对应数据 commit，更新 Skill 后才读取维护者指定的新快照；没有自动实时同步承诺。快照公开不等于每条观点、图片、评论或外部链接都已独立核验。

默认检索使用中英文词法、中文双字切分与术语扩展；AI 的语义判断发生在问题改写、回读和重排阶段，不冒充已启用神经向量。相似分数与结构检查均不代表正确率。最新产品机制、实验外推和具体站点归因需要相应证据。

主分支只分发轻量 Skill 与脚本，不附带私人 SQLite、账户配置、令牌、模型或全量原始资料。原始资料与观点的权利归相应作者，引用不表示作者为项目背书。

### 维护者更新资料

以下只供拥有源库的维护者执行，普通安装者不需要准备这些路径。

1. `scripts/reconcile_sources.py --vault <原库> --manifest <既有映射> --snapshot <旧快照data> --output-dir <检查目录>` 生成派生清单和差异，列出新增正文、正文变化、导航排除与待分类候选；不修改原 Markdown 或原映射。
2. 用生成的 `derived-manifest.json` 运行既有 `geo_kb.py build`，再用 `export_remote.py` 导出正文快照。六篇官方说明继续通过 `--supplement-dir assets/source-notes` 补入。
3. `scripts/export_assets.py --vault <原库> --output <快照data> --report <检查报告.json>` 补齐版本化附件映射和最终完整性清单。检查 missing、ambiguous 与 scan_errors，再验证旧正文版本和引用行号。
4. 对实际问题做文档与段落回归后发布数据 commit，并更新 Skill 内的固定 commit、manifest 哈希及软件文件清单。公开资料变更与软件发布分别可追溯；不能只更新一份 README 的数量。

派生清单经核对后可作为下次扫描的既有映射。正文重新导出后应重新运行附件导出，避免最终 manifest 丢掉媒体。原文发布日期缺失时继续保留未知。

## 历史版本与可选旧 MCP

默认流程已改为 Skill 直接查询 GitHub。下面保留已有 MCP 发布、配置与排障说明供维护者选择旧接口时查阅，不作为本版安装或问答步骤，不自动修改已有 MCP 设置。

<!-- REMOTE_DEPLOYMENT_STATUS -->
v0.4.0 线上 MCP 于 2026-11-05 的更新记录保持不变；本轮 GitHub Skill 发布不代表旧 MCP 已运行新流程。[历史测试记录](references/release-v0.4.0.md) · [Claude/Grok 历史回答](references/claude-grok-example.md)

<!-- FALLBACK_VERIFICATION_STATUS -->
历史上 v0.3.0 验证过 MCP 403 后转 GitHub 的通道与逐行定位；这不构成本轮新版本的回答验收。

<details>
<summary>展开历史 MCP 连接与显式 auto 模式说明（非默认）</summary>

## MCP 返回 403 时怎么办

旧 v0.4 默认曾使用 `auto`；本版只在明确选择 `--transport auto` 时沿用这项历史行为：先尝试内置地址的 MCP；遇到连接失败、403、超时或无效协议响应时，再按需读取公开的 GitHub 知识快照。两个通道使用固定版本的源资料，都保留原文和出处。检索没有结果、参数错误或引用核对不通过，不是换通道补答案的理由。自定义其他 MCP 地址时不会擅自切回维护者的知识库。

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


</details>

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
