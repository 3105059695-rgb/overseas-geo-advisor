# 海外 GEO Skill：一句安装指令

适用于支持安装 Skill、执行 Python 脚本和联网的 AI 客户端。普通纯聊天网页不能仅凭提示词安装。

```text
请安装 overseas-geo-advisor：https://github.com/3105059695-rgb/overseas-geo-advisor
```

规则已经内置在 [SKILL.md](../SKILL.md) 与 [答题与时效规则](answer-guide.md)。安装助手应读取它们并按 [首次接入步骤](connection.md#安装助手的首次接入步骤)验证真实检索；用户无需另外粘贴长提示词，无需配置 MCP 或导入资料。

安装后直接提问，例如：“Claude 和 Grok 更喜欢引用哪些信源？”或“我的英文网站该怎么做 GEO？”客户端需要重新加载时按提示操作；没有自动识别技能时可加 `$overseas-geo-advisor`。

仅凭名字不能保证所有 AI 找到仓库，所以首次转发保留链接。“最新”指对变化信息在当次回答时联网核查，保留实际数据日期；不是整个知识库实时同步，也不是所有问题都有最新研究。
