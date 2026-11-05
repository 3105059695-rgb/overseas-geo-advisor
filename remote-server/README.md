# 远程服务维护

普通用户使用 README 中的远程 MCP 地址，无需部署这些文件。

`worker.mjs` 是 v0.2.0 已发布服务的 Worker ESM 源码副本。Cloudflare Workers 或兼容 ESM `fetch` 的托管环境可运行它；它没有 npm 依赖，也不调用付费生成模型。实例部署参数由维护者管理，不包含在 Skill 包中。

数据固定到 `knowledge-snapshot` 分支的一个完整 Git commit。`DATA_BASE` 是公开数据地址，不是凭据。更换快照需要先导出、核对并发布数据，再更新此常量及线上 Worker。

```text
python scripts/export_remote.py --db <knowledge.sqlite3> --output <data-checkout>/data --report <report.json>
```

维护顺序：本地索引更新 → 导出报告与凭证模式检查 → 数据分支提交发布 → 固定新 commit → Worker 测试部署 → 无登录 HTTP MCP 测试。不要把个人配置、数据库、对话历史或凭据提交到代码仓库。

当前源资料 977 份、6,559 个片段，数据 commit 为 `c548b2ef186d75e8119ce23cda55f6fe87dbae0b`。精确正文及行号可供回读；不包含图片文件或图片 OCR。代码部署和 Obsidian 内容更新是两件事，当前没有自动实时同步任务。

公开接口均只读：`ask_geo`、`search_geo`、`read_geo_source`、`browse_geo_topics`、`check_geo_answer`。检索采用词法与中文双字切分；引用结构核对不证明语义正确，也不能将历史档案升级为现行机制或效果保证。
