# v0.1 实现范围与接口

## 本版组成

本版采用现有模型客户端作为讲解者，本地工具提供检索、不可变版本原文、核对过的样稿和结构检查。不包含在线商业服务、服务端自由文本模型生成或向量模型。检索基线的效果要由实际问题检验，后续再决定是否增加语义检索和重排。

`GeoKB` 数据库保存在 Skill 文件夹外。分发 Skill 不会自动获得维护者的私人知识库；另一台电脑需连接经授权的资料或以后部署的远程服务。

## 工具职责

| 工具 | 返回与边界 |
|---|---|
| ask_geo | 对已覆盖问题提供来源样稿，其他问题提供候选证据包；明确 answer_kind 和 gaps |
| search_geo | 词法、中文分词与术语扩展检索；相似分数不是正确率 |
| read_geo_source | 按 document_id、source_version 和行号读取历史快照；不接收任意文件路径 |
| review_geo_claim | 记录本次 AI 对新断言的核对，验证摘录和版本；只允许作者报告、来源定义、历史表述，不得升级为独立验证 |
| browse_geo_topics | 资料覆盖和工具当前状态 |
| check_geo_answer | 校验引用、版本与证据使用资格；不证明语义支持或独立有效性 |

`review_geo_claim` 成功后返回 `claim_id`、`claim.conditions` 与 `citation.citation_id`。结构检查的每项 claim 应传 `text`、`kind`、`main`、`reviewed_claim_id`、`citation_ids`、`allowed_use`、`conditions`，其中条件使用工具返回的完整集合。`kind=definition` 对应来源定义，`kind=author_report` 对应作者报告，`kind=historical_report` 对应历史归因。逐项选择具体 claim_id，避免把同一片段里其他断言的核验范围借给当前结论。

`current_fact`、`current_mechanism`、`priority`、`core_number` 需要各自明确的更高资格及核验范围；本版普通会话核对不能创建这些资格。公式可以按 `definition` 解释来源口径，但不能因此批准新的统计数字或投入排序。

## 追问

`previous_answer_id` 指向工具保存的上一轮结果；`focus_citation_id` 指向被追问的真实引用。`as_of` 明确历史时间。`context` 只传回答需要的业务条件，用户观察放入 `context.observations`，返回结果中标记为 `user_provided`。

指代无法从这些信息明确解析时，应返回澄清状态。不要把“第二个”强行解释成第二篇文章或第二个渠道。

引用需包含 document_id、source_version、line_start、line_end，快照随版本保存。数据更新后仍可按原版本取回；若该版本不存在，明确返回无法读取，不能静默读取最新版本。

## 状态与发布边界

`answered` 表示工具提供了其声明范围内的结果，不代表所有内容经过独立事实验证。`partial`/`insufficient_evidence` 表示存在缺口；`needs_clarification` 表示必要范围或指代不明；`unavailable` 表示工具无法完成查询。

源资料默认为未审核。匹配上真实摘录及来源版本、且规则允许的种子断言可按范围使用；对其他命中，可以在原文阅读后通过 review_geo_claim 做本次断言登记。登记只验证文本对应并记录 AI 自述的语义核对，不产生当前机制或独立效果资格。种子样稿由 AI 按原文整理，不能称为人工专家已审。不能根据一次索引成功宣称全文完整、图片可读、日期最新或全部评论齐全。

SDK 客户端的真实握手和工具调用可验证协议链路。用户 AI 的最终自然语言呈现，需要另外记录真实客户端结果；本轮若未完成，就保留未验证状态。40题独立验收由未使用其答案调试的人实施，不把开发题测试当独立验收。

开发题、最终证据包、主结论与独立验收的具体评分见 [评测说明](evaluation.md)。
