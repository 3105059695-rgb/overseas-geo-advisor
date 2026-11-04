# 海外 GEO 知识顾问

根据已连接的知识库，解释海外 AI 搜索产品、信源分类、GEO 实操方法、指标、论文和案例，并保留来源、日期与适用条件。

**当前版本：v0.1.0，本地 Skill + CLI + stdio MCP。** 用户自己的 AI 负责讲解，配套工具负责检索、读取指定版本原文、记录断言核对和检查引用资格。

公开这个仓库提供的是 Skill 和工具代码。**仓库不包含维护者的 977 份私人资料全文，也没有已经部署的共享在线知识库地址。** 使用者需要连接自己的授权 Markdown 资料。仓库中的 22 个种子断言、3 份答案样稿用于说明证据规则与回答方式，不等于附带完整知识库。

## 可以用来做什么

- 解释海外 AI 产品的资料收录范围，区分历史提及与当前功能核查。
- 解释信源的不同分类维度，以及为什么分类不能直接变成渠道投入排名。
- 阅读方法、论文和案例，说明作者观点、实验条件与不能外推的部分。
- 给出有出处的 GEO 执行框架和通用排查顺序。
- 追问“这个结论来自哪里”，按文档版本与行号读取依据。

遇到资料不足，工具会保留缺口；没有实际站点材料时，只能给通用排查假设，不作确定归因。

## 快速安装

需要 Python 3.11 或更新版本，以及支持 FTS5 的 SQLite。CLI 检索使用 Python 标准库，不需要下载向量模型。优先复用已经安装的 Python。

### 1. 安装 Skill

支持 Skills 的客户端可将本仓库放到其 Skill 目录。以 Codex 为例，PowerShell 中执行：

```powershell
$skillDir = Join-Path $HOME ".codex/skills/overseas-geo-advisor"
git clone https://github.com/3105059695-rgb/overseas-geo-advisor.git $skillDir
Set-Location $skillDir
```

macOS 或 Linux Shell：

```bash
git clone https://github.com/3105059695-rgb/overseas-geo-advisor.git ~/.codex/skills/overseas-geo-advisor
cd ~/.codex/skills/overseas-geo-advisor
```

已有同名目录时先确认其用途，不要覆盖。其他 AI 工具按自身支持的 Skill 安装位置处理；仅支持 MCP 的客户端可以直接使用后面的 MCP 接入方式。

### 2. 连接自己的资料

把下面两个占位路径替换为本机实际路径，索引目录必须放在原资料目录之外：

```text
python -B -X utf8 scripts/geo.py setup --vault "<授权Markdown资料目录>" --data-dir "<独立索引目录>"
python -B -X utf8 scripts/geo.py status
python -B -X utf8 scripts/geo.py search --question "海外信源怎么分？" --limit 8
python -B -X utf8 scripts/geo.py ask --question "海外信源怎么分？"
```

`setup` 读取原始资料，写入独立索引和本用户配置，不修改源文件。普通查询无需重新构建索引。再次执行相同配置的 `setup` 可以更新索引并保留历史版本。

种子样稿依赖特定原文及版本；自己的资料库不包含这些原文时，工具会报告缺失，并按实际资料返回候选证据，不伪造样稿依据。新命中的资料可在 AI 阅读上下文后逐项记录有限用途的核对。

完整连接、配置位置与历史引用操作见 [连接说明](references/connection.md)。

### 3. 在 AI 中提问

在已识别 Skill、并能执行本地工具的客户端中，可以这样说：

> 使用 $overseas-geo-advisor，详细解释海外信源怎么分类。请给出知识库依据，并说明哪些信息不足以支持渠道投入顺序。

也可以问：

- “知识库收录了哪些海外 AI 搜索产品？哪些能力仍需当前核查？”
- “品牌提及、引用份额与 SoV 的统计口径有什么区别？”
- “这个案例适合我的业务吗？先说明它的适用条件。”
- “海外 GEO 怎么操作？请解释每一步的目的、产出和依据。”

CLI 的 `ask` 返回结构化结果。`curated_answer` 表示来源样稿；`evidence_packet` 表示仍需 AI 阅读和解释的候选证据包。二者都不等于独立专家已经核验的答案。

## MCP 接入（可选）

本地 stdio MCP 另需 Python `mcp` SDK；本版测试版本是 `mcp==1.26.0`。先使用已有的兼容环境。若尚未安装、并决定在当前 Python 环境安装，可执行：

```text
python -m pip install "mcp==1.26.0"
python -B -X utf8 scripts/geo.py mcp-config
```

第二条命令生成当前解释器、脚本与数据库的实际连接配置，不修改客户端的全局设置。将配置填入支持本地 stdio MCP 的客户端；不同客户端可能需要转换配置格式。

服务由客户端作为本地进程启动，不开放 HTTP 端口。它使用当前本地账户的访问范围，没有提供远程多用户鉴权。

| 工具 | 用途 |
|---|---|
| `ask_geo` | 查询专业问题，返回来源样稿或证据包，并明确范围和缺口 |
| `search_geo` | 使用词法、中文分词和术语扩展查找相关片段 |
| `read_geo_source` | 按文档 ID、版本和行号读取原文 |
| `review_geo_claim` | 记录本次 AI 对断言的核对；只允许作者报告、来源定义或历史表述 |
| `browse_geo_topics` | 查看资料覆盖、目录和当前能力 |
| `check_geo_answer` | 检查引用定位及证据使用资格，不证明语义正确性 |

原资料始终保持只读；追问记录和断言核对写入本地派生数据库。接口和状态含义见 [实现范围与接口](references/runtime-contract.md)。

## 怎样约束回答

1. 先理解用户问题中的产品、功能模式、市场、时间和业务背景。
2. 搜索资料，再读取必要上下文，保留方法、结果、条件与局限。
3. 每项重要结论对应真实片段；同一论文的原文、译文和笔记不算多份独立证据。
4. 区分来源定义、作者经验、历史表述、综合建议和教学示例。
5. 未核验的数字或机制只作查证线索，不用于核心结论和行动优先级。
6. 引用绑定原文版本；资料更新后，仍可回查当时采用的内容。

`review_geo_claim` 验证指定版本中存在对应原文，并记录回答 AI 的核对声明。它不能独立证明文章事实或方法效果，也不能批准当前产品机制或渠道排序。`check_geo_answer` 的结构检查通过同样不代表答案内容通过专家验收。

更多规则与实例：

- [证据与回答规则](references/evidence-policy.md)
- [40 个开发问题的覆盖范围](references/coverage.md)
- [三份真实资料答案样稿](references/answer-samples.md)
- [评测方式与验收边界](references/evaluation.md)

## 验证范围

本版已在开发环境通过 **26 项自动行为测试**，涵盖版本回读、同源片段、引用篡改、断言用途、配置、追问以及 MCP SDK 成功和失败路径。已使用官方 Python SDK 客户端完成 stdio 握手与实际工具调用。

运行测试：

```text
python -B -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```

MCP 测试需要对应 SDK；没有 SDK 时，相关测试会跳过，应如实记录跳过情况。

以下仍需单独验证：独立 40 题专业内容验收、真实图形 AI 客户端最终展示、当前产品机制和可用性，以及使用者的原文链接和图片访问权限。测试通过不构成“零错误”保证。

## 仓库结构

```text
overseas-geo-advisor/
├── SKILL.md                       # AI 使用规则
├── agents/openai.yaml             # Skill 展示信息
├── assets/curated.json             # 有范围的种子断言、目录与样稿
├── scripts/
│   ├── geo.py                     # 配置与命令入口
│   ├── geo_kb.py                  # 索引、检索、版本与证据资格
│   └── geo_mcp.py                 # 本地 stdio MCP
├── references/                    # 规则、覆盖表、样稿和接入说明
└── tests/                         # 行为测试及开发问题
```

数据库、用户配置、私人资料全文及服务凭据不随仓库发布。公开引用资料和原始观点的权利归相应作者；引用仅说明出处，不表示作者为本项目背书，也不将第三方材料重新授予统一许可。

如果要让不同用户连接同一个在线知识库，需要另行部署远程服务，明确访问范围、鉴权、运行费用和客户端兼容性。公开本仓库不会自动公开或托管任何人的本地知识库。
