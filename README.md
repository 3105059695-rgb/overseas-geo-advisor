# 海外 GEO 知识顾问

安装这个 Skill 后，让你的 AI 查询维护者提供的 GEO 知识库，再依据原文回答专业问题。**普通使用者不需要准备或导入资料，不需要知识库账号或 API Key。**

适合问海外 AI 搜索产品、信源分类、GEO 操作方法、指标、论文和案例。工具负责找到证据和回读原文，你正在使用的 AI 负责中文讲解，保留来源、日期、适用条件与证据缺口。

当前代码版本 **v0.2.0**。共享快照有 **977 份文档、6,559 个检索片段**，按来源归为 833 组；不等于 833 份经人工核验的独立证据。

<!-- REMOTE_DEPLOYMENT_STATUS -->
**已于 2026-11-05 发布并完成免登录实测。** 正式 MCP 客户端成功发现五个工具，三个真实问题的引用原文与源快照逐行一致。服务连通与引用定位已验证；这不等于独立的专业语义验收。

## 最简单的使用方式

把仓库链接发给支持安装 Skills、执行脚本的 AI，并说：

> 安装这个海外 GEO Skill：https://github.com/3105059695-rgb/overseas-geo-advisor 。使用它自带的共享远程知识库，不导入我自己的资料。安装后查询“海外信源怎么分”，给出知识库原文依据。

安装权限与目录由客户端决定。支持远程 MCP 的客户端也可直接连接下面的地址；同时安装 Skill，能让 AI 使用本项目的阅读、引用和讲解规则。

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

已有同名目录时不要覆盖，确认属于本项目后按正常 Git 更新流程处理。其他客户端使用自身 Skill 目录。安装 Skill 不会自动改写 MCP 全局设置；没有 MCP 时，AI 可调用内置远程脚本。

新安装没有本地配置时，`geo.py ask/search/read/browse/check` 自动使用远程库。有旧本地配置时保持原行为，`--remote` 明确切换至共享服务。详见 [连接说明](references/connection.md)。

## 直接这样提问

> 使用 $overseas-geo-advisor，详细解释海外信源怎么分。先读取知识库相关原文，给出来源、例子和适用条件，不要按模型记忆补齐。

- “知识库收录了哪些海外 AI 搜索产品？哪些信息只是历史记录？”
- “我的英文 B2B 网站怎样开始 GEO？做什么、产出什么、如何检查？”
- “品牌提及率、引用份额和 SoV 的分母有什么区别？”
- “这个 Reddit 方法适合我的业务吗？保留原帖问题、回答和反驳意见。”
- “刚才的结论出自哪段原文？解释相关上下文。”

`evidence_packet` 是候选证据包，AI 仍需阅读原文后写答案，不是已核验的成品答案。查询失败应明确失败；没有对应证据应说明缺口。

## 回答如何保留依据

1. 按问题检索，再读取真正采用的原文段落。
2. 引用保留来源链接、文档版本和行号，能回到当时采用的内容。
3. 同源的原文、译文、笔记归组，不重复增加证据数量。
4. 区分作者经验、定义、历史说明、综合建议和教学例子。
5. 数字、现行机制和优先级不因“有引用”就成为确定事实。

服务只读，不允许访客修改知识库或给全库写审核记录，不保存服务器端对话历史。追问需要 AI 结合当前对话明确问题或引用。`check_geo_answer` 只核对引用结构、摘录和允许用途，不等于专家审核或语义正确保证。

## 更新与限制

远程库是维护者发布的版本快照，不依赖使用者的电脑。新增 Obsidian/飞书资料后，维护者需重新导出发布；使用者继续使用同一 MCP 地址。当前没有自动实时同步承诺。

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
