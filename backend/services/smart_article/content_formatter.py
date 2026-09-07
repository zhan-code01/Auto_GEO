from __future__ import annotations

import html
import re


MARKDOWN_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*(?:\r?\n|$)")
HTML_H1_RE = re.compile(r"^\s*<h1\b[^>]*>(.*?)</h1>\s*", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")

# 注册公司名常见后缀/描述词/地域前缀。文章经常省略这些成分（如
# "广州百盛千鲜食品有限公司" → "百盛千鲜"），但首次出现仍需挂上官网链接。
_COMMON_COMPANY_SUFFIXES = [
    "有限公司",
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "集团公司",
    "股份公司",
    "公司",
    "集团",
    "股份",
]
_COMMON_COMPANY_DESCRIPTORS = [
    "科技",
    "信息",
    "文化",
    "传媒",
    "网络",
    "智能",
    "咨询",
    "服务",
    "实业",
    "贸易",
    "食品",
    "生物",
    "农业",
    "餐饮",
    "供应链",
    "电子商务",
    "电子",
    "商务",
    "技术",
    "软件",
    "硬件",
    "设备",
    "制造",
    "工程",
]
_COMMON_LOCATION_PREFIXES = [
    "广州市",
    "深圳市",
    "北京市",
    "上海市",
    "杭州市",
    "苏州市",
    "成都市",
    "武汉市",
    "南京市",
    "重庆市",
    "天津市",
    "西安市",
    "郑州市",
    "长沙市",
    "青岛市",
    "宁波市",
    "无锡市",
    "佛山市",
    "东莞市",
    "厦门市",
    "福州市",
    "济南市",
    "沈阳市",
    "大连市",
    "哈尔滨市",
    "长春市",
    "石家庄市",
    "太原市",
    "呼和浩特市",
    "合肥市",
    "南昌市",
    "昆明市",
    "贵阳市",
    "南宁市",
    "兰州市",
    "银川市",
    "西宁市",
    "乌鲁木齐市",
    "拉萨市",
    "海口",
    "三亚",
    "珠海",
    "汕头",
    "湛江",
    "江门",
    "肇庆",
    "惠州",
    "中山",
    "佛山",
    "东莞",
    "广州",
    "深圳",
    "北京",
    "上海",
    "杭州",
    "苏州",
    "成都",
    "武汉",
    "南京",
    "重庆",
    "天津",
    "西安",
    "郑州",
    "长沙",
    "青岛",
    "宁波",
    "无锡",
]


def remove_duplicate_leading_title(content: str, title: str) -> str:
    """Remove only a leading H1 whose visible text equals the article title."""
    if not content or not title:
        return content

    markdown_match = MARKDOWN_H1_RE.match(content)
    if markdown_match and _normalize(markdown_match.group(1)) == _normalize(title):
        return content[markdown_match.end() :].lstrip()

    html_match = HTML_H1_RE.match(content)
    if html_match:
        visible_text = HTML_TAG_RE.sub("", html_match.group(1))
        if _normalize(html.unescape(visible_text)) == _normalize(title):
            return content[html_match.end() :].lstrip()

    return content


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().casefold()


def normalize_website_url(website: str) -> str:
    """补全官网URL协议头；空值返回空字符串。"""
    value = (website or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = f"https://{value}"
    return value


def _company_name_variants(name: str) -> list[str]:
    """生成公司名的可能简称变体，优先保留较长、较具体的匹配。

    例如 "广州百盛千鲜食品有限公司" 可产生：
    ["广州百盛千鲜食品有限公司", "广州百盛千鲜食品", "广州百盛千鲜",
     "百盛千鲜食品有限公司", "百盛千鲜食品", "百盛千鲜"]
    """
    variants = {name}

    # 迭代剥掉常见公司后缀
    stripped = name
    changed = True
    while changed:
        changed = False
        for suffix in _COMMON_COMPANY_SUFFIXES:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                changed = True
                break
    if len(stripped) >= 3:
        variants.add(stripped)

    # 从原始名和去后缀名各剥一次行业描述词
    sources = [name, stripped]
    for source in sources:
        for descriptor in _COMMON_COMPANY_DESCRIPTORS:
            if source.endswith(descriptor):
                variant = source[: -len(descriptor)]
                if len(variant) >= 3:
                    variants.add(variant)

    # 剥常见地域前缀（如广州、北京、上海等）
    for variant in list(variants):
        for prefix in _COMMON_LOCATION_PREFIXES:
            if variant.startswith(prefix):
                without_prefix = variant[len(prefix) :]
                if len(without_prefix) >= 4:
                    variants.add(without_prefix)

    # 按长度降序：优先匹配最长、最具体的形式
    return sorted((v for v in variants if len(v) >= 3), key=len, reverse=True)


def ensure_company_website_link(content: str, company_name: str, website: str) -> tuple[str, bool]:
    """确定性兜底：保证正文首次出现公司名（含常见简称变体）处带官网链接。

    - 已存在 [...](...) 链接则不重复添加；
    - 跳过标题行、图片占位符行和已处于链接内的出现位置；
    - 支持公司简称：如"广州百盛千鲜食品有限公司"可匹配文章中的"百盛千鲜"；
    - 官网或公司名为空时原样返回，(content, False)。
    """
    name = (company_name or "").strip()
    url = normalize_website_url(website)
    if not content or not name or not url:
        return content, False

    variants = _company_name_variants(name)
    # 任一已知变体已链接即视为完成
    for variant in variants:
        if f"[{variant}](" in content:
            return content, True

    lines = content.split("\n")
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "{{IMAGE_SLOT:" in line:
            continue
        pos = 0
        while pos < len(line):
            matched_variant = ""
            for variant in variants:
                if line.startswith(variant, pos) and len(variant) > len(matched_variant):
                    matched_variant = variant
            if matched_variant and not _inside_markdown_link(line, pos):
                lines[index] = f"{line[:pos]}[{matched_variant}]({url}){line[pos + len(matched_variant) :]}"
                return "\n".join(lines), True
            pos += 1
    return content, False


def _inside_markdown_link(line: str, pos: int) -> bool:
    """判断位置pos是否已处于 [text](url) 链接的text或url部分。"""
    open_bracket = line.rfind("[", 0, pos)
    if open_bracket != -1:
        close_bracket = line.find("]", open_bracket)
        if (
            close_bracket != -1
            and close_bracket >= pos
            and close_bracket + 1 < len(line)
            and line[close_bracket + 1] == "("
        ):
            return True
    open_paren = line.rfind("](", 0, pos)
    if open_paren != -1 and line.find(")", open_paren) >= pos:
        return True
    return False
