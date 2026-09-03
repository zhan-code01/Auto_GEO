from backend.services.playwright.ai_platforms.deepseek import DeepSeekChecker
from backend.services.playwright.ai_platforms.doubao import DoubaoChecker
from backend.services.playwright.ai_platforms.base import AIPlatformChecker


def test_deepseek_rejects_sidebar_history_fragment():
    assert not DeepSeekChecker._looks_like_answer(
        "Correcting Python Tensor Reshaping Syntax\n"
        "这个计算对比学习的内容 df InfoNCE(pred_seq\n"
        "import pandas as pd df = pd.rea",
        "广州鲲界科技有限公司的核心产品是什么？",
    )


def test_deepseek_extracts_answer_after_current_question():
    checker = DeepSeekChecker("deepseek", {"name": "DeepSeek", "url": "https://chat.deepseek.com"})
    body_text = "\n".join(
        [
            "开启新对话",
            "7 天内",
            "Correcting Python Tensor Reshaping Syntax",
            "这个计算对比学习的内容 df InfoNCE(pred_seq",
            "广州鲲界科技有限公司的核心产品是什么？",
            "广州鲲界科技有限公司的核心产品主要是企业内容增长自动化平台。",
            "它覆盖知识库管理、AI内容生成、分发发布和GEO效果监测等模块。",
            "复制",
            "重新生成",
        ]
    )

    answer = checker._extract_answer_from_text(body_text, "广州鲲界科技有限公司的核心产品是什么？")

    assert "企业内容增长自动化平台" in answer
    assert "Correcting Python Tensor" not in answer
    assert "重新生成" not in answer


def test_deepseek_does_not_use_history_body_without_current_question():
    checker = DeepSeekChecker("deepseek", {"name": "DeepSeek", "url": "https://chat.deepseek.com"})
    history_body = "\n".join(
        [
            "女生颜值客观分析",
            "2025-12",
            "GRU4Rec和Caser论文引用指南",
            "Correcting Python Tensor Reshaping Syntax",
            "这个计算对比学习的内容 def InfoNCE(pred_seq",
            "import pandas as pd df = pd.rea",
            "给我描述一下deepseak使用了什么技术",
        ]
    )

    answer = checker._extract_answer_from_text(history_body, "广州鲲界科技有限公司的核心产品是什么？")

    assert answer == ""


def test_doubao_rejects_sidebar_menu_as_answer():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    text = "\n".join(
        [
            "开启新对话",
            "历史对话",
            "主对话",
            "帮我写作",
            "AI 创作",
            "云盘",
            "发现",
            "更多",
            "快捷方式",
        ]
    )

    assert not checker._is_valid_answer(text, "广州鲲界科技有限公司的核心产品是什么？")


def test_doubao_accepts_natural_answer_text():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    text = (
        "本地化 AI 数字员工通常在数据安全上更有保障，因为数据处理、存储和权限控制主要留在企业内部环境。"
        "云端 AI 员工的优势是部署快、弹性强，但需要重点评估传输加密、供应商合规、日志留存和数据隔离策略。"
        "如果企业处理客户隐私、财务数据或核心业务资料，应优先选择本地化或私有化部署。"
    )

    assert checker._is_valid_answer(text, "本地化AI数字员工与云端AI员工在数据安全上哪个更有保障？")


def test_answer_quality_accepts_doubao_structured_search_answer():
    text = "\n".join(
        [
            "什么是口碑好的AI知识获取能力推荐个靠谱的？推荐哪家公司？",
            "搜索 3 个关键词，参考 18 篇资料",
            "一、什么是口碑好的 AI 知识获取能力",
            "核心标准（评判靠谱 AI 知识检索的 4 个关键）：",
            "低幻觉、可溯源：回答附带资料来源链接或文献出处，不编造事实，能区分无答案和推测答案；",
            "实时联网 + 长文本精读：可抓取最新资讯、论文、行业报告，支持上传 PDF/Word/网页批量读取专业资料；",
            "RAG 知识库能力：能自建私有知识库，仅基于自有资料作答，不泄露内部数据；",
            "二、分场景靠谱厂商与产品推荐（2026 实测口碑）",
            "场景 1：个人日常学习、深度调研、写论文（C 端工具）",
            "1. 字节跳动｜豆包",
            "核心优势：国内综合口碑靠前，免费额度充足，原生联网检索，自带 RAG 文档知识库。",
        ]
    )

    result = AIPlatformChecker.validate_answer_quality(
        text,
        "什么是口碑好的AI知识获取能力推荐个靠谱的？推荐哪家公司？",
    )

    assert result["valid"], result


def test_answer_quality_still_rejects_short_suggestion_list():
    text = "\n".join(
        [
            "给我一些原创小说的写作灵感",
            "AI 工具中的总结功能如何优化?",
            "请分享一些提高英文口语的小技巧",
        ]
    )

    result = AIPlatformChecker.validate_answer_quality(text, "广州鲲界科技有限公司的主营业务包括哪些？")

    assert not result["valid"]


def test_doubao_rejects_search_suggestion_list_with_company_terms():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    text = "\n".join(
        [
            "GEO智慧增长引擎客户服务",
            "广州鲲界科技智能客服优势",
            "广州鲲界科技有限公司核心产品",
            "广州鲲界科技有限公司介绍",
            "广州鲲界科技有限公司主营业务概述",
        ]
    )

    assert not checker._is_valid_answer(text, "广州鲲界科技有限公司是一家什么样的互联网公司？")


def test_doubao_clean_text_removes_search_header_and_followups():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    raw = "\n".join(
        [
            "搜索 2 个关键词， 广州鲲界科技有限公司主营业务 结合工商登记经营范围与企业业务宣传信息，分为核心技术业务、电商生鲜食品贸易、策划文创服务、配套综合服务四大板块：",
            "一、核心软件与信息技术业务（企业主业方向）",
            "软件开发：通用软件、数字文化创意软件、网络与信息安全软件开发、软件外包服务；",
            "业务总结",
            "公司以软件信息技术开发、企业 AI 数字化解决方案为技术核心。",
            "参考 9 篇资料",
            "广州鲲界科技有限公司的核心技术业务在行业内处于什么水平？",
            "广州鲲界科技有限公司的联系方式是什么？",
        ]
    )

    cleaned = checker._clean_text(raw)

    assert cleaned.startswith("广州鲲界科技有限公司主营业务")
    assert "搜索 2 个关键词" not in cleaned
    assert "参考 9 篇资料" not in cleaned
    assert "联系方式是什么" not in cleaned


def test_doubao_clean_text_keeps_structured_answer_start():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    raw = (
        "搜索 3 个关键词， 广州鲲界科技有限公司完整介绍 "
        "一、基础工商信息 成立时间：2026 年 01 月 04 日。"
    )

    cleaned = checker._clean_text(raw)

    assert cleaned.startswith("广州鲲界科技有限公司完整介绍")
    assert "一、基础工商信息" in cleaned
    assert "搜索 3 个关键词" not in cleaned


def test_doubao_clean_text_preserves_answer_line_breaks():
    checker = DoubaoChecker("doubao", {"name": "豆包", "url": "https://www.doubao.com"})
    raw = "\n".join(
        [
            "广州鲲界科技有限公司主营业务",
            "一、核心技术研发业务（主营核心）",
            "1. 软件开发：通用软件、网络信息安全软件开发。",
            "二、农产品、预包装食品线上线下零售批发",
        ]
    )

    cleaned = checker._clean_text(raw)

    assert "\n一、核心技术研发业务" in cleaned
    assert "\n1. 软件开发" in cleaned
    assert "\n二、农产品" in cleaned
