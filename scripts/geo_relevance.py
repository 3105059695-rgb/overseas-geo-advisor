"""Conservative lexical relevance hints, not a semantic or factual approval.

Keep the requested engine in scope and separate source-mechanism candidates
from mentions of an engine used to write SEO copy. The answerer must still
read each excerpt and verify the actual assertion, date and product mode.
"""
from __future__ import annotations

import re

PLATFORM_ALIASES = {
    "Claude": ("claude", "anthropic", "claudebot", "claude-user", "claude-searchbot", "克劳德"),
    "Grok": ("grok", "xai", "x.ai"),
    "ChatGPT": ("chatgpt", "openai", "oai-searchbot", "gptbot"),
    "Perplexity": ("perplexity", "perplexitybot"),
    "Gemini": ("gemini",),
    "Copilot": ("copilot", "bing chat"),
    "Google AI Overviews": ("ai overview", "ai overviews", "google aio", "谷歌ai概览"),
    "Google AI Mode": ("ai mode", "谷歌ai模式"),
    "DeepSeek": ("deepseek", "深度求索"),
    "豆包": ("豆包", "doubao"),
    "元宝": ("元宝", "腾讯元宝"),
    "Kimi": ("kimi", "月之暗面"),
}


def _has_alias(text: str, alias: str) -> bool:
    if re.search(r"[\u3400-\u9fff]", alias):
        return alias in text.lower()
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text, re.I))


def platforms_in(text: str) -> list[str]:
    return [name for name, aliases in PLATFORM_ALIASES.items() if any(_has_alias(text, a) for a in aliases)]


def query_intent(question: str) -> dict:
    platforms = platforms_in(question)
    alias_assumptions = []
    # Bare GPT is a common shorthand in a consumer-source question. It is not
    # an alias for a model family, research experiment, or developer API.
    if ("ChatGPT" not in platforms
            and re.search(r"(?<![a-z0-9_-])gpt(?![a-z0-9_-])", question, re.I)
            and re.search(r"信源|来源|引用|网站|联网|偏好|喜欢|\b(?:sources?|citations?|prefer\w*|websites?)\b", question, re.I)
            and not re.search(r"训练|预训练|模型|论文|研究|实验|架构|\b(?:api|model|research|paper|training|architecture)\b", question, re.I)):
        platforms.append("ChatGPT")
        alias_assumptions.append({"input": "GPT", "resolved_platform": "ChatGPT",
                                  "reason": "在本题信源语境中按 ChatGPT 口语简称检索，不代表 GPT 模型或 API。"})
    source_words = bool(re.search(r"信源|来源|引用|信息.{0,6}(?:来自|哪里)|从哪|哪(?:里|些网站)|搜索渠道|联网|"
                                  r"(?:喜欢|偏好|偏向|更常).{0,20}(?:网站|官网|网页|社区|论坛|新闻|Reddit|Wikipedia|维基)|"
                                  r"\b(?:sources?|citations?|cites?|search|retriev\w*|prefer\w*)\b", question, re.I))
    other_task = bool(re.search(r"费用|价格|收费|计费|多少钱|\b(?:price|pricing|cost)\b|"
                               r"(?:如何|怎么|怎样).{0,8}(?:让|提高|提升|优化|监控|跟踪|追踪)|"
                               r"(?:不|没|未).{0,4}引用.{0,6}(?:我|我们)|"
                               r"\b(?:optimize|optimise|track|monitor)\b", question, re.I))
    selection = "explicit" if platforms else "not_specified"
    if (not platforms and source_words and not other_task
            and not re.search(r"分类|类型|类别|怎么分|如何分|\bcategor\w*\b", question, re.I)
            and re.search(r"海外|国外|\b(?:overseas|international)\b", question, re.I)
            and re.search(r"ai|人工智能|大模型|助手", question, re.I)
            and re.search(r"不同|各|分别|比较|对比|哪些|\b(?:different|each|compare)\b", question, re.I)):
        # This is a disclosed comparison scope, not an exhaustive product list.
        platforms = ["ChatGPT", "Claude", "Grok", "Perplexity", "Gemini", "Copilot"]
        selection = "illustrative_overseas_scope"
    kind = "platform_sources" if platforms and source_words and not other_task else "general"
    aspects = []
    if kind == "platform_sources":
        if re.search(r"训练|training", question, re.I):
            aspects = ["training_data"]
        elif re.search(r"占比|比例|份额|百分比|统计|排名|\b(?:share|percentage|ranking|statistics)\b", question, re.I):
            aspects = ["observed_preferences"]
        elif re.search(r"偏好|喜欢|偏向|更常|\bprefer\w*\b", question, re.I):
            aspects = ["content_sources", "observed_preferences"]
        else:
            aspects = ["retrieval_channels", "content_sources", "observed_preferences"]
    requested_mode = "api" if re.search(r"\bapi\b", question, re.I) else "research_model" if re.search(
        r"模型|论文|研究|实验|\b(?:model|research|paper|experiment)\b", question, re.I) else "consumer_or_unspecified"
    return {"kind": kind, "platforms": platforms, "source_aspects": aspects, "platform_selection": selection,
            "platform_alias_assumptions": alias_assumptions, "requested_mode": requested_mode}


def entity_terms(intent: dict) -> list[str]:
    # Index uses Latin words/hyphenated tokens; x.ai therefore also needs xai.
    return list(dict.fromkeys(a for p in intent["platforms"] for a in PLATFORM_ALIASES[p]
                             if " " not in a and "." not in a))


_SOURCE_RELATION = re.compile(
    r"联网搜索|网络搜索|网页搜索|搜索工具|搜索结果|搜索索引|实时(?:网络|网页)|"
    r"(?:获取|抓取|收集|检索|读取).{0,16}(?:网页|页面|网络|内容|数据)|"
    r"(?:引用|信源|来源).{0,12}(?:来自|包括|偏好|偏向|倾向|最多|主要|网站|域名|社区|新闻)|"
    r"(?:来自|偏好|偏向|倾向|使用).{0,12}(?:来源|网站|域名|Reddit|维基)|"
    r"\b(?:web[ _-]?search|x[ _-]?search|searchbot|search results|search index|fetch\w*|crawl\w*|"
    r"retriev\w*|cit(?:e|es|ed|ing)|sources?\s+(?:from|include|are)|"
    r"brave|bing|reddit|wikipedia)\b|\bsearch(?:es|ing)?\s+(?:the\s+|public\s+)?(?:web|internet|x\b)|"
    r"\bcitations?\s+(?:to|from|include)\b|维基百科|Claude-User|Claude-SearchBot", re.I)
_PREFERENCE = re.compile(r"引用|信源|来源|官网|网站|新闻|域名|维基|\b(?:sources?|citat\w*|cited|cite|domains?|reddit|wikipedia)\b", re.I)
_STUDY = re.compile(r"占比|比例|份额|样本|实验|调查|观测|研究|统计|\b(?:study|sample|observed|percentage|share|experiment|survey)\b", re.I)
_OPINION = re.compile(r"建议.{0,30}(?:开放|推出|发布)|希望.{0,30}(?:开放|推出|发布)|可以成为|应该成为|"
                      r"\b(?:could be|should launch|should open|wish|please launch|open grok search)\b", re.I)
_OPERATOR = re.compile(r"(?:粘贴|交给|复制到|上传到|上传给|让|使用|用).{0,12}(?:claude|grok|chatgpt).{0,25}(?:写|整理|生成|制作|分析|汇总|提取)|"
                       r"(?:claude|grok).{0,12}(?:seo|插件|机器人|智能体|agent)|\bgrok\s+bot\b|"
                       r"\b(?:paste|give|ask|use|using|with).{0,30}(?:claude|grok).{0,35}(?:write|draft|extract|build|seo|agent)\b", re.I)

_OBSERVATION = re.compile(r"\d+(?:\.\d+)?\s*%|占比|比例|份额|引用率|频率|排名|最常|最多|更多|更常|偏好|偏向|倾向|"
                          r"\b(?:prefer\w*|most|more|less|frequen\w*|top|rank\w*|dominant|percentage|share)\b", re.I)
_CRAWL = re.compile(r"抓取|爬虫|\bcrawl\w*\b|searchbot", re.I)
_CITATION_ACTION = re.compile(r"引用|被引|\b(?:citat\w*|cited|cites?|citing)\b", re.I)
_TRAINING = re.compile(r"训练|预训练|\b(?:training|pretraining|pre-training|trained)\b|gptbot|claudebot", re.I)
_OPTIMIZATION = re.compile(r"优化|优化内容|提高.{0,10}引用|提升.{0,10}引用|\b(?:optimi[sz]\w*|seo|geo strategies)\b", re.I)
_LIMITATION = re.compile(r"局限|限制|仅限|仅适用|不代表|不能|无法|未知|未披露|不适用|样本|实验|测试期间|"
                         r"\b(?:limit\w*|only|cannot|does not|do not|not necessarily|unknown|sample|experiment|caveat)\b", re.I)


def _body_units(text: str) -> list[str]:
    # Headings and links may nominate a document but cannot support a claim.
    lines = [line for line in text.splitlines()
             if not re.match(r"^#{1,6}\s|^[-*]?\s*(?:原文|来源|原标题|原帖|source|original_url|title)\s*[:：]", line.strip(), re.I)
             and not re.match(r"^(?:[-*]\s*)?(?:\[\[[^\n]+\]\]|\[[^\]]+\]\([^)]+\))\s*$", line.strip())]
    return [s.strip() for s in re.split(r"\n|(?<=[。！？!?])\s*|(?<=[.;])\s+", "\n".join(lines)) if s.strip()]


def _relation(unit: str, context: str) -> str:
    if _OPINION.search(unit):
        return "background"
    if _OPERATOR.search(unit) or _OPTIMIZATION.search(unit):
        return "content_optimization"
    if _TRAINING.search(unit):
        return "training"
    if (_PREFERENCE.search(unit) and _OBSERVATION.search(unit)
            and (not _CRAWL.search(unit) or _CITATION_ACTION.search(unit))
            and (_STUDY.search(context) or re.search(r"\d+(?:\.\d+)?\s*%|占比|引用率|most cited|cited most", unit, re.I))):
        return "observed_preference"
    if _SOURCE_RELATION.search(unit):
        return "retrieval_channel"
    return "background"


def _mode(unit: str) -> str:
    if re.search(r"\bapi\b|开发者接口", unit, re.I):
        return "api"
    if (re.search(r"\bgpt[- ]?\d|\blanguage models?\b|基础模型|语言模型", unit, re.I)
            and not re.search(r"chatgpt|聊天产品|消费端", unit, re.I)):
        return "research_model"
    return "unspecified"


def _scoped_units(title: str, text: str):
    """Resolve only an explicit pronoun to one unambiguous local platform.

    This is a retrieval hint. A title alone, unrelated sentence, mixed title,
    or a different engine never supplies the missing source relationship.
    """
    active = platforms_in(title)
    active = active if len(active) == 1 else []
    active_mode = _mode(title)
    result = []
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s", line.strip()):
            named = platforms_in(line)
            if named:
                active = named if len(named) == 1 else []
                active_mode = _mode(line)
            continue
        for unit in _body_units(line):
            named = platforms_in(unit)
            inherited = False
            if named:
                active = named if len(named) == 1 else []
                active_mode = _mode(unit)
            elif active and re.match(r"^(?:它(?:们)?|该(?:助手|平台|产品|服务)|这个(?:助手|平台|产品)|it\b|its\b|this (?:assistant|platform|product|service)\b|the (?:assistant|service)\b)", unit, re.I):
                named, inherited = active[:], True
            result.append((unit, named, inherited, active_mode if inherited else _mode(unit)))
    return result


def passage_relevance(intent: dict, title: str, text: str) -> dict:
    targets = intent["platforms"]
    scoped = _scoped_units(title, text)
    title_platforms = platforms_in(title)
    found = set(platforms_in(text)) | {p for _, named, _, _ in scoped for p in named}
    if len(title_platforms) == 1:
        found.update(title_platforms)
    matched = [p for p in targets if p in found]
    units = [unit for unit, _, _, _ in scoped]
    classified = [(unit, _relation(unit, text), mode, named, inherited) for unit, named, inherited, mode in scoped]
    relevant_units = [(unit, relation, mode) for unit, relation, mode, named, _ in classified
                      if not targets or any(p in named for p in targets)]
    relations = list(dict.fromkeys(relation for _, relation, _ in relevant_units if relation != "background")) or ["background"]
    platform_relations = {p: list(dict.fromkeys(relation for unit, relation, _, named, _ in classified
                                               if p in named)) for p in matched}
    preference_query = "observed_preferences" in intent["source_aspects"] and "retrieval_channels" not in intent["source_aspects"]
    priority = (["observed_preference", "retrieval_channel", "training", "content_optimization", "background"]
                if preference_query else ["training", "retrieval_channel", "observed_preference", "content_optimization", "background"])
    result = {"matched_platforms": matched, "direct_platforms": [], "tier": "background",
              "reason": "仅有平台提及，尚未定位回答本题的信源说明。", "semantic_validation": "not_performed",
              "relation_type": next(r for r in priority if r in relations), "relation_types": relations,
              "relation_method": "lexical_hint_not_semantic_validation", "platform_relations": platform_relations,
              "context_inherited_platforms": sorted({p for _, _, _, named, inherited in classified if inherited for p in named if p in targets}),
              "product_modes": list(dict.fromkeys(mode for _, _, mode in relevant_units)),
              "limitations": [unit[:1000] for unit in units if _LIMITATION.search(unit)][:8]}
    if not targets:
        return {**result, "tier": "direct_candidate", "reason": "词法匹配候选，需回读判断。"}
    if not matched:
        return {**result, "reason": "返回片段未提及所问平台。"}
    if intent["kind"] != "platform_sources":
        return {**result, "direct_platforms": matched, "tier": "direct_candidate", "reason": "片段提及所问平台；尚需核对问题关系。"}
    if _OPINION.search(title):
        return {**result, "reason": "建议或愿望类来源，不证明平台现行信源。"}
    direct = []
    for platform in matched:
        for unit, relation, mode, named, inherited in classified:
            if platform not in named or unit.endswith(("?", "？")):
                continue
            if _OPINION.search(unit) or _OPERATOR.search(unit):
                continue
            if mode in {"api", "research_model"} and mode != intent.get("requested_mode"):
                continue
            if intent["source_aspects"] == ["training_data"]:
                useful = relation == "training" and bool(_SOURCE_RELATION.search(unit))
            elif preference_query:
                useful = relation == "observed_preference"
            else:
                useful = relation in {"retrieval_channel", "observed_preference"} or bool(
                    relation == "background" and _SOURCE_RELATION.search(unit))
                # Names in benchmark tables and non-source overlap metrics do
                # not answer where an engine gets information.
                if _STUDY.search(unit) and not re.search(r"Brave|Bing|Reddit|Wikipedia|维基|新闻|社区|官网|文档|网站|网页|\b(?:web|domains?|sites?|news)\b", unit, re.I):
                    useful = False
            if useful:
                direct.append(platform)
                break
    reason = "语句直接提及平台或以代词承接唯一平台，并含信源描述；须核对指代、实际含义、模式和日期。" if direct else result["reason"]
    if preference_query and not direct:
        reason = "本片段未定位所问平台的观测偏好证据；搜索渠道、爬虫或可访问性只能作背景。"
    return {**result, "direct_platforms": direct, "tier": "direct_candidate" if direct else "background", "reason": reason}


def balanced_select(candidates: list[dict], platforms: list[str], limit: int, key: str = "direct_platforms",
                    max_per_document: int | None = None, max_per_work: int | None = None) -> list[dict]:
    """Ensure each named engine has a turn, without padding from other engines."""
    chosen, seen, counts = [], set(), {"document_id": {}, "work_id": {}}
    def group(item, field):
        return item.get(field) or item.get("citation", {}).get(field) or item.get("chunk", {}).get(field)
    def permitted(item):
        return item["id"] not in seen and all(not cap or not group(item, field)
                                             or counts[field].get(group(item, field), 0) < cap
                                             for field, cap in (("document_id", max_per_document), ("work_id", max_per_work)))
    def choose(item):
        chosen.append(item)
        seen.add(item["id"])
        for field in counts:
            value = group(item, field)
            if value:
                counts[field][value] = counts[field].get(value, 0) + 1
    if platforms:
        queues = [[c for c in candidates if p in c["relevance"][key]] for p in platforms]
        while len(chosen) < limit:
            progressed = False
            for queue in queues:
                while queue and not permitted(queue[0]):
                    queue.pop(0)
                if queue and len(chosen) < limit:
                    item = queue.pop(0)
                    choose(item)
                    progressed = True
            if not progressed:
                break
    for item in candidates:
        if len(chosen) >= limit:
            break
        if permitted(item):
            choose(item)
    return chosen


def platform_coverage(intent: dict, citations: list[dict], background: list[dict]) -> list[dict]:
    result = []
    for platform in intent["platforms"]:
        direct = sum(platform in c.get("relevance", {}).get("direct_platforms", []) for c in citations)
        related = sum(platform in c.get("relevance", {}).get("matched_platforms", []) for c in background)
        result.append({"platform": platform, "direct_candidates": direct, "background_candidates": related,
                       "status": "candidate_evidence" if direct else "background_only" if related else "not_found_in_retrieval"})
    return result


def answer_brief(question: str, intent: dict, coverage: list[dict]) -> dict:
    source_question = intent["kind"] == "platform_sources"
    aspects = intent["source_aspects"]
    focus = "直接回答用户本题，先结论再解释。"
    if source_question:
        focus = "分别解释所问平台从哪里取得信息、可引用什么；有偏好证据才谈偏好。"
        if aspects == ["training_data"]:
            focus = "解释所问平台训练数据的已知来源与未知范围；不要用实时搜索来源冒充训练数据。"
        elif aspects == ["observed_preferences"]:
            focus = "回答来源占比或排名，明确平台、样本、模式、时间与分母；没有数据就说本次未找到。"
        elif aspects == ["content_sources", "observed_preferences"]:
            focus = "回答所问平台在什么条件下更常引用哪些网站或来源类型；可访问不等于偏好，没有比较证据就明确缺口。"
    return {"user_question": question, "reader_level": "beginner", "platforms": intent["platforms"],
            "focus": focus,
            "platform_selection": intent.get("platform_selection", "explicit" if intent["platforms"] else "not_specified"),
            "scope_note": "本次示例比较 ChatGPT、Claude、Grok、Perplexity、Gemini、Copilot；不是全部海外AI清单。先说明范围，再按证据回答。" if intent.get("platform_selection") == "illustrative_overseas_scope" else "以用户明确指定的平台与问题为准。",
            "source_aspects": intent["source_aspects"],
            "must_answer": [f"{p}：先给本题有依据的直接回答；缺少的部分明确说本次未找到。" for p in intent["platforms"]],
            "avoid": ["不要把搜索渠道、具体被引网站和训练数据混为一谈。", "不要用其他平台研究或SEO写作流程填充本题。",
                      "不要把样本占比外推为固定偏好。", "不要把有限候选检索说成读完全部资料或全库不存在。"],
            "missing_direct_evidence": [c["platform"] for c in coverage if not c["direct_candidates"]],
            "evidence_display": "关键结论就近附来源链接和支持它的短摘录；分别说明查询成功、原文读取和语义支持。",
            "example_rule": "用小白能懂的例子解释术语；教学例子明确标注，不编造真实结果。"}
