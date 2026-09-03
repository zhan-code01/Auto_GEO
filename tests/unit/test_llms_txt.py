# -*- coding: utf-8 -*-
"""llms.txt 渲染器 + 配置驱动建站接入的单测。

纯单测，无 DB / 无网络。覆盖：
  - strip_html 去标签 + 折叠空白
  - render_llms_txt 各 section 渲染、缺失字段容错、services 无双空行（回归）
  - SiteGeneratorService 的 config → llms 数据适配（含 <br> 清理、扁平 contact 转嵌套）
  - SiteGeneratorService.generate_site 落盘 llms.txt（输出重定向到 tmp_path，不污染真实目录）
"""

import pytest

from backend.services.llms_txt import render_llms_txt, strip_html
from backend.services.site_generator import SiteGeneratorService


# ==================== strip_html ====================

def test_strip_html_removes_br_and_collapses_whitespace():
    assert strip_html("连接全球<br>极速送达") == "连接全球 极速送达"


def test_strip_html_handles_empty_and_none():
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_strip_html_strips_generic_tags():
    assert strip_html("<b>粗体</b> <i>斜体</i>") == "粗体 斜体"


# ==================== render_llms_txt ====================

def _full_data():
    return {
        "company_name": "测试科技有限公司",
        "slogan": "连接全球<br>极速送达",
        "industry": "物流",
        "description": "一家提供极速物流服务的公司。",
        "about_intro": "成立于 2010 年，团队 50+。",
        "stats": [{"value": "15", "unit": "+", "label": "年经验"}],
        "services": [{"icon": "fa-plane", "title": "航空速运", "desc": "全球次日达"}],
        "advantages": ["7x24 支持", "行业领先技术"],
        "cases": [{"tag": "电商", "title": "黑五保障", "desc": "0 爆仓"}],
        "qualifications": [{"title": "ISO 9001", "desc": "质量认证"}],
        "contact": {"phone": "400-1", "email": "a@b.com", "address": "上海"},
    }


def test_render_llms_txt_full_has_all_sections():
    out = render_llms_txt(_full_data())
    assert out.startswith("# 测试科技有限公司")
    # slogan 已去 <br>
    assert "**Slogan:** 连接全球 极速送达" in out
    for section in [
        "## 企业概述",
        "## 关于我们",
        "## 核心数据",
        "## 主营业务与解决方案",
        "## 核心优势",
        "## 典型客户案例",
        "## 资质荣誉",
        "## 联系方式",
        "## 页面导航",
    ]:
        assert section in out
    assert "### [fa-plane] 航空速运" in out
    assert "电话: 400-1" in out


def test_render_llms_txt_minimal_only_company_name():
    out = render_llms_txt({"company_name": "极简公司"})
    assert out.startswith("# 极简公司")
    # 没有相应数据时，可选 section 不应出现
    assert "## 主营业务与解决方案" not in out
    assert "## 联系方式" not in out
    # 页面导航永远在（至少首页）
    assert "## 页面导航" in out
    assert "[首页](/index.html)" in out


def test_render_llms_txt_empty_data_does_not_crash():
    out = render_llms_txt({})
    assert out.startswith("# 企业官网")  # 默认标题兜底


def test_render_llms_txt_services_has_no_double_blank_lines():
    """services 块不应出现连续空行（回归 services 多空行修复）。只传 services 避免其他块干扰。"""
    out = render_llms_txt({
        "company_name": "X",
        "services": [{"title": "S1", "desc": "D1"}, {"title": "S2", "desc": "D2"}],
    })
    assert "\n\n\n" not in out


# ==================== config → llms 数据适配 ====================

def _sample_config():
    """模拟前端 ConfigWizard.vue 提交的 config（formData）。"""
    return {
        "company_name": "Turbo Logistics",
        "company_slogan_hero": "连接全球<br>极速送达",
        "company_description_hero": "比传统物流快 30%。",
        "company_about_intro": "拥有 50+ 工程师。",
        "company_features": ["行业领先技术", "   ", "7x24 支持"],  # 含一个空白项
        "stats": [{"value": "200", "unit": "个", "label": "国家"}],
        "services": [{"icon": "plane", "title": "航空速运", "desc": "次日达"}],
        "cases": [{"title": "黑五", "tag": "电商", "desc": "0 爆仓", "image": ""}],
        "qualifications": [{"title": "ISO", "desc": "认证"}],
        "contact_phone": "400-2",
        "contact_email": "x@y.com",
        "contact_address": "上海浦东",
    }


def test_adapt_config_maps_fields_and_strips_html():
    svc = SiteGeneratorService()
    adapted = svc._adapt_config_to_llms_data(_sample_config())

    assert adapted["company_name"] == "Turbo Logistics"
    assert adapted["slogan"] == "连接全球 极速送达"          # <br> 去除
    assert adapted["description"] == "比传统物流快 30%。"
    assert adapted["about_intro"] == "拥有 50+ 工程师。"
    # company_features → advantages，空白项被过滤
    assert adapted["advantages"] == ["行业领先技术", "7x24 支持"]
    # 扁平 contact → 嵌套
    assert adapted["contact"] == {"phone": "400-2", "email": "x@y.com", "address": "上海浦东"}


def test_adapt_config_then_render_is_valid_llms_txt():
    """适配结果喂给 render_llms_txt 应产出含公司名 + 联系方式的 llms.txt。"""
    svc = SiteGeneratorService()
    out = render_llms_txt(svc._adapt_config_to_llms_data(_sample_config()))
    assert out.startswith("# Turbo Logistics")
    assert "电话: 400-2" in out
    assert "邮箱: x@y.com" in out


# ==================== generate_site 落盘 ====================

def test_generate_site_writes_llms_txt(tmp_path):
    """generate_site 应在站点目录产出 llms.txt；输出重定向到 tmp_path 不污染真实目录。"""
    svc = SiteGeneratorService()
    svc.output_dir = str(tmp_path)  # 重定向，避免写真实 static/sites

    site_id = "test-site-0001"
    result = svc.generate_site(site_id, _sample_config(), template_id="corporate")

    llms_file = tmp_path / site_id / "llms.txt"
    assert llms_file.exists(), "llms.txt 未生成"
    content = llms_file.read_text(encoding="utf-8")
    assert content.startswith("# Turbo Logistics")
    assert "## 联系方式" in content
    # 返回值带 llms_url
    assert result.get("llms_url") == f"/static/sites/{site_id}/llms.txt"
    # index.html 也应存在
    assert (tmp_path / site_id / "index.html").exists()


def test_generate_site_llms_failure_does_not_block_html(tmp_path, monkeypatch):
    """llms.txt 生成失败时不应阻断 index.html（独立 try/except）。"""

    def _boom(_data):
        raise RuntimeError("适配炸了")

    svc = SiteGeneratorService()
    svc.output_dir = str(tmp_path)
    monkeypatch.setattr(svc, "_adapt_config_to_llms_data", _boom)

    site_id = "test-site-0002"
    result = svc.generate_site(site_id, {"company_name": "X"}, template_id="corporate")

    # HTML 仍生成
    assert (tmp_path / site_id / "index.html").exists()
    # llms.txt 因异常未生成，但不影响 build 成功返回
    assert not (tmp_path / site_id / "llms.txt").exists()
    assert "preview_url" in result
