# Grok 的 Web Search：互联网网页来源与域名筛选

- 原文链接：https://docs.x.ai/developers/tools/web-search
- 原文标题：Web Search
- 核查日期：2026-11-05
- 资料类型：官方开发文档的中文核查笔记；不是全文翻译
- 适用范围：启用 web_search 工具的 Grok API 调用

## Grok 的网页信源

官方开发文档说明，Web Search 让 Grok 实时搜索互联网、打开网页并提取回答需要的信息。开发者可以设置允许或排除的域名，限制这一请求搜索哪些网站。这里的域名筛选是调用者施加的条件，不能当作 Grok 自带的固定网站偏好。

## 原文短摘录

> search the web in real-time and browse web pages

## 给小白的解释与边界

教学例子：一项查询被限制只搜索品牌官网时，返回的引用当然可能集中在官网；不能把这项测试当作所有 Grok 用户的信源分布。网页搜索能力证明 Grok 不止能看 X，但本页没有证明它更喜欢 Reddit、新闻媒体或任何固定网站名单。
