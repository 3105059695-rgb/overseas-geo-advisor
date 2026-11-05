# Claude 信源入口：搜索爬虫、用户读取与训练爬虫的区别

- 原文链接：https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler
- 原文标题：Does Anthropic crawl data from the web, and how can site owners block the crawler?
- 核查日期：2026-11-05
- 资料类型：官方帮助文档的中文核查笔记；不是全文翻译
- 适用范围：Anthropic 公布的三个机器人用途

## 三个入口分别做什么

官方区分三种用途：ClaudeBot 收集可能用于训练的网页；Claude-User 在用户发起请求时访问网站；Claude-SearchBot 获取、分析在线内容，以改善搜索结果的相关性和准确性。网站可以分别设置这些机器人访问权限。

## 原文短摘录

> Claude-SearchBot navigates the web to improve search result quality for users.

这句话说明搜索机器人的用途，不说明最终会引用哪个域名。

## 给小白的解释与边界

“以前学过的知识”“为这次问题去打开网页”“为搜索发现内容”不是同一件事。官网说明，禁止搜索或用户访问机器人可能降低内容在相关搜索中的可见度；允许访问也不等于保证被引用。教学例子：检查日志时，把三种机器人分开记录，不能把一次 ClaudeBot 访问当作回答已引用你的网站。
