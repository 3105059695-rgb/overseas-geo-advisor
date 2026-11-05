# v0.2 实现范围与接口

## 组成与来源

用户的 AI 是讲解者，共享远程工具提供词法检索、不可变版本原文和引用结构检查。服务器不调用付费生成模型，不进行向量检索或独立事实审核。实测发布状态见 README；真实工具响应才是查询完成的依据。

普通用户无需本地资料。维护者更新源资料后需重新导出和发布云端快照，不是自动实时同步。原文保留版本与行号，历史回读不能静默改用新版本。

## 远程工具

| 工具 | 参数与边界 |
|---|---|
| `ask_geo` | `question`，可选 `context`、`focus_citation_id`、`as_of`、`detail`；返回证据包和缺口，AI 仍需阅读原文 |
| `search_geo` | `question`、`limit` 1–20、可选 `as_of`；词法、中文双字切分与术语扩展，分数不是正确率 |
| `read_geo_source` | `document_id`、`source_version`、`start_line`、可选 `end_line`；最多 400 行/30,000 字符，按 `next_start_line` 续读 |
| `browse_geo_topics` | 资料统计、分类、目录和当前能力 |
| `check_geo_answer` | `bundle`；核对真实引用、版本、摘录和允许用途，不验证语义正确性 |

问题最多 8,000 字符，请求体最多 128 KiB，只传必要背景。用户观察放 `context.observations`，不得升级为知识库证据。原文工具不接受任意 URL 或机器路径。

没有远程 `review_geo_claim`，不保存全局用户审核记录和对话历史。`previous_answer_id` 无法解析本机之外的聊天，缺少明确问题时应澄清。追问需要 AI 改写指代并传真实引用，不凭“第二个”猜测对象。

## 远程引用检查

采用服务返回的真实引用 ID，格式为 `文档ID@版本:L起始行-L结束行`。不要自行编造。以下占位内容须替换为刚刚读取的真实内容：

```json
{
  "claims": [
    {
      "text": "作者提出：……",
      "kind": "author_report",
      "main": true,
      "allowed_use": "attributed_report",
      "citation_ids": ["<工具返回的真实citation_id>"],
      "exact_quote": "<对应来源的连续原文摘录>",
      "conditions": ["<方法适用的实际条件>"]
    }
  ]
}
```

CLI 使用 `geo.py --remote check --bundle-file <UTF8 JSON路径>`。有限来源用途为 `attributed_report`、`definition`、`historical`，陈述类型可分别用 `author_report`、`definition`、`historical_report`。解释来源定义不能因此批准新统计数字或预算排序。

连续摘录、版本和行号匹配只说明定位成功；`semantic_validation=not_performed`、`answer_approved=false`。AI 仍需对照上下文逐句判断是否支持陈述。现行事实、机制、确定效果、全局排名和行动优先级不能仅凭真实摘录获批。

## 状态与证据

`partial`/`insufficient_evidence` 表示缺口，`needs_clarification` 表示范围或指代不明，`unavailable` 表示没有完成查询。`evidence_packet` 不是已核验完整答案；样稿也只适用于其来源和范围。

源资料默认只是候选线索。AI 阅读、核对翻译或摘录不等于独立验证效果。同源归组是程序规则结果，不是人工独立性审计；文件数不说明图片、评论、全文翻译和日期都完整核验。

引用保留 `document_id`、`source_version`、`line_start`、`line_end` 和真实链接。优先用公开 `reading_url` 回读，不要求外部用户访问维护者本机或私人飞书页。

## 本地模式差异

本地 `GeoKB` 使用 Skill 目录外的 SQLite，保留六工具 stdio MCP。本地 ask 可保存本机 `answer_id`，review 可写本机派生核对记录，均不修改源文档。

本地 review 返回 `claim_id`、`claim.conditions` 和 `citation.citation_id`。本地 check 的 claim 需要 `text`、`kind`、`main`、`reviewed_claim_id`、`citation_ids`、`allowed_use`、`conditions`。这与远程连续摘录检查不同，不能混用。

本地普通会话 review 仅登记作者报告、来源定义和历史说明，不能创建 `current_fact`、`current_mechanism`、`priority`、`core_number` 的更高资格。结构检查通过不等于语义支持或专家验收。

## 验证边界

HTTP MCP 官方 SDK 握手、工具调用、匿名访问和版本回读属于协议及行为验证。用户 AI 最终中文答案、图形界面和专业正确性需要分别验证。40 个开发问题不是独立保留题验收。详见 [评测说明](evaluation.md)。
