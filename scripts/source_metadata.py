"""Conservative metadata extraction from explicit source-header fields only."""
from datetime import date
from pathlib import Path
import re

SOURCE_LABEL = re.compile(r"^(?:source|source[_ ]?url|original[_ ]?url|原帖(?:链接|地址|来源)?|原文(?:链接|地址|网址|来源)?|原始(?:链接|地址|网址|来源)|来源(?:链接|地址|网址)?|原链接|原视频(?:链接)?|视频链接|原论文(?:链接)?|论文链接|帖子链接)$", re.I)
PUBLICATION_LABEL = re.compile(r"^(?:(?:原帖|原文|原始)?(?:发布时间|发布日期|发表时间|发表日期)|发帖时间|发布|published(?:_at| date)?|publication(?: date)?|日期)(?:\s*UTC)?$", re.I)
DATE_KINDS = (
    ("updated", re.compile(r"^(?:更新(?:时间|日期)?|最后更新(?:时间|日期)?|updated(?:_at)?|last[_ ]updated)$", re.I)),
    ("sampled", re.compile(r"^(?:采样(?:时间|日期)?|抽样(?:时间|日期)?|sampled(?:_at)?)$", re.I)),
    ("collected", re.compile(r"^(?:(?:收集|收录|归档|采集)(?:时间|日期)?|collected(?:_at)?|archived(?:_at)?)$", re.I)),
    ("organized", re.compile(r"^整理(?:时间|日期)$", re.I)),
    ("checked", re.compile(r"^(?:核查日期|核验日期|checked(?:_at)?|reviewed(?:_on)?)$", re.I)),
    ("source_version", re.compile(r"^source[_ ]version$", re.I)),
)
DAY = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})(?!\d)")
URL = re.compile(r"https?://[^\s<>\]\)\"']+")


def _date_value(raw):
    match = DAY.search(raw)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat(), "day"
        except ValueError:
            return None, "invalid"
    month = re.search(r"(?<!\d)((?:19|20)\d{2})\s*[-/年]\s*(\d{1,2})(?!\d)", raw)
    if month:
        year, number = map(int, month.groups())
        return (f"{year:04d}-{number:02d}", "month") if 1 <= number <= 12 else (None, "invalid")
    year = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw)
    return (year[1], "year") if year else (None, "unknown")


def _plain(raw):
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw).strip().strip("\"'")


def source_role(relative):
    path = Path(relative)
    return "navigation" if (path.name == "01_检索范围与收录说明.md"
        or any(part in {"收集记录", "整理记录", "99_整理记录"} for part in path.parts)
        or "交付标准及进度" in path.name) else "source_content"


def extract_metadata(text, relative, canonical_url):
    top = text.splitlines()[:90]
    title = next((re.sub(r"^#+\s*", "", line).strip() for line in top if re.match(r"^#\s", line)), Path(relative).stem)
    kind = "paper_related" if "论文" in relative else "discussion" if "reddit" in relative.lower() else "archived_article"
    result = dict(title=title, original_url=None, published_at=None, source_type=kind,
                  retrieval_role=source_role(relative), source_dates=[], metadata_provenance={})
    for number, line in enumerate(top, 1):
        if re.match(r"^#{2,6}\s", line):
            break
        # Inline bold fields occur in Reddit headers; retain their physical line.
        fields = [re.sub(r"^\s*[-*>]\s*", "", line).replace("**", "").strip()]
        fields.extend(label + ":" + value for label, value in re.findall(r"\*\*([^*：:]+)[：:]\*\*\s*(.*?)(?=\s*\|?\s*\*\*|$)", line))
        for field in fields:
            match = re.match(r"^([^：:]+)\s*[:：]\s*(.*)$", field)
            if not match:
                continue
            label, raw = match[1].strip(), match[2].strip().strip("\"'")
            provenance = {"line": number, "label": label, "raw": raw}
            if SOURCE_LABEL.fullmatch(label) and not result["original_url"]:
                for url in URL.findall(raw):
                    candidate = canonical_url(url)
                    if candidate and not re.search(r"(?:feishu\.cn|larksuite\.com)/", candidate, re.I):
                        result["original_url"] = candidate
                        result["metadata_provenance"]["original_url"] = provenance
                        break
            date_kind = "published" if PUBLICATION_LABEL.fullmatch(label) else next((kind for kind, pattern in DATE_KINDS if pattern.fullmatch(label)), None)
            if date_kind:
                value, precision = _date_value(raw)
                item = dict(provenance, kind=date_kind, date=value, date_precision=precision)
                if item not in result["source_dates"]:
                    result["source_dates"].append(item)
                if date_kind == "published" and precision == "day" and not result["published_at"]:
                    result["published_at"] = value
                    result["publication_date_origin"] = "explicit_source_field"
                    result["metadata_provenance"]["published_at"] = provenance
                if date_kind in {"updated", "sampled", "collected", "checked"} and precision == "day":
                    result.setdefault(date_kind + "_at", value)
            dest = None
            if re.fullmatch(r"作者|原文作者|author|authors|楼主|讲师", label, re.I):
                dest = "author"
            elif re.fullmatch(r"原文标题|原始标题|原课程|original[_ ]title", label, re.I):
                dest = "original_title"
            elif re.fullmatch(r"出版社|发布机构|publisher", label, re.I):
                dest = "publisher"
            if dest and raw and dest not in result:
                result[dest] = _plain(raw)
                result["metadata_provenance"][dest] = provenance
    return result
