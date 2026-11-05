# Claude / Grok 信源：真实知识库问答样例

> 2026-11-05 使用 v0.4.0 的 GitHub 通道完成。以下保留测试回答；它是本题的参考表达，不是后续问题的固定答案。后续使用仍须检索与回读，产品信息也应注意日期。

你问的“信源”，我先按**联网回答时从哪里找资料、用了哪些网页或帖子**来讲。

**Claude 可以搜索互联网、读取你给的网址；Grok 可以搜索公开 X 帖子和互联网网页。至于“比较喜欢哪些网站”，Claude 有历史研究给出过具体例子；Grok 本次查到的资料还不足以给出可靠的网站排名。**

**Claude 怎么找资料？**

知识库收录的《Enable and use web search》官方文档笔记，核查日期是 **2026 年 11 月 5 日**。其中记录：Claude 会搜索与问题相关的网页，综合多个来源，并在回答中给出来源链接；你直接发网址，它也可以读取文章、博客等页面。笔记保留的官方短句是：

> “Claude processes multiple sources to find relevant content.”
> 中文意思：Claude 会处理多个来源，寻找相关内容。

所以，你可以把它理解成一个会替你查网页、整理材料的助手。**“上哪里找”是搜索渠道，“最后用了哪篇文章”才是这次回答的具体信源。** [库内笔记](https://github.com/3105059695-rgb/overseas-geo-advisor/blob/71b3bf759adef477fb2e72df5797ae83f38717a4/data/documents/doc-565f4b9e527244e04393/f6f6045ef306fb7f040a63b1d67a9cf49e141cdcfdc7431e4935b2d40445914e.json) · [官方原文入口](https://support.claude.com/en/articles/10684626-enable-and-use-web-search)

**Claude 比较喜欢哪些网站？有例子，但要看问题和时期。**

知识库里有一篇 **2025 年 9 月 10 日**的论文译稿《Generative Engine Optimization: How to Dominate AI Search》。研究者用 Claude 3.5 Sonnet 的程序接口开启网页搜索，提出产品排名类问题，每次收集最多十个链接。作者在两个行业报告了这些主要来源：

| 当时问的领域 | 论文报告的 Claude 主要来源 | 用普通话理解 |
|---|---|---|
| 消费电子，如手机、电脑 | TechRadar、Tom’s Guide、RTINGS | 科技媒体、产品评测网站 |
| 汽车 | Consumer Reports、Car and Driver、US News | 消费评测、汽车媒体和排名类内容 |

库内译文的对应句子是：“**Claude主要用TechRadar、Tom’s Guide、RTINGS**”；汽车部分写的是“**Claude偏Consumer Reports、Car and Driver、US News**”。因此，这份实验支持的说法是：**当时在这些产品排名问题上，Claude 较多采用专业媒体和第三方评测内容。** [论文译稿，第 4.1、5.2.2 节](https://github.com/3105059695-rgb/overseas-geo-advisor/blob/71b3bf759adef477fb2e72df5797ae83f38717a4/data/documents/doc-ba75a02a7686e747f73e/541579afd178a1dffa66abcee46359a564b4bb96413385d4b2ea6547ba7db1b3.json) · [原论文 v1](https://arxiv.org/abs/2509.08919v1)

这份名单可以帮助你认识它曾经引用过什么，不能当作今天所有 Claude 问题的固定推荐名单。本次没有重新跑实验，也没有核查这些网站今天的引用频次。

**Grok 怎么找资料？**

知识库收录的 X 官方《About Grok》笔记，同样标注 **2026 年 11 月 5 日核查**：Grok 回答问题时，可以决定搜索公开 X 帖子，也可以进行实时互联网搜索。资料保留的官方短句是：

> “conduct a real-time web search on the Internet”
> 中文意思：在互联网上进行实时网页搜索。

因此，公开 X 帖子和普通网页都属于它可使用的来源渠道，但并非每次回答都会把两种渠道全部用上。举个**教学例子**：问一家公司的新产品，最终出处可能是公司网页，也可能是公开发布帖；要看那次回答实际附了什么链接，这不是一次实测结果。 [库内笔记](https://github.com/3105059695-rgb/overseas-geo-advisor/blob/71b3bf759adef477fb2e72df5797ae83f38717a4/data/documents/doc-2d96d5774bf76a623cfb/b09b18cd67f63905c4651c9599329a56ffaa84b2d6f36c2f114bec3f4a4b35e0.json) · [X 官方原文入口](https://help.x.com/en/using-x/about-grok)

**Grok 到底更喜欢 X、Reddit，还是新闻网站？本次还不能排出来。** 能搜索 X，不能直接推出“引用最多的是 X”。我补查了 Grok 与 Reddit 的资料，回读的材料还不足以核对其比较样本、具体模式和统计条件，所以不能把“Grok 最喜欢 Reddit”当作确定结论。看见一次引用，也只能说明这次用了这个来源。

本次通过 **GitHub 知识库快照**做了 6 次检索，回读了 6 份不同资料的相关正文，采用其中 3 份支撑上面的回答。采用的是 2 份官方文档中文核查笔记和 1 份论文译稿；本次没有另外打开官网复核，也没有把搜索命中当作全部读过。
