# -*- coding: utf-8 -*-

import sys
import types

from backend.services.document_extractor import DocumentExtractor


def test_document_extractor_falls_back_to_conversation_llm_config(monkeypatch):
    import backend.services.document_extractor as document_extractor

    monkeypatch.setattr(document_extractor, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(document_extractor, "DEEPSEEK_API_URL", "")
    monkeypatch.setattr(document_extractor, "AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setattr(document_extractor, "AUTOGEO_CONVERSATION_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(document_extractor, "AUTOGEO_CONVERSATION_LLM_MODEL", "deepseek-test")

    extractor = DocumentExtractor()

    assert extractor.api_key == "conversation-key"
    assert extractor.api_url == "https://example.test/v1"
    assert extractor.model == "deepseek-test"


def test_extract_pdf_text_uses_pypdf(monkeypatch):
    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakePdfReader:
        is_encrypted = False

        def __init__(self, _stream):
            self.pages = [
                FakePage("第一页   产品介绍\r\n核心能力"),
                FakePage("第二页\n\n\n客户案例"),
            ]

    fake_module = types.SimpleNamespace(PdfReader=FakePdfReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)

    text = DocumentExtractor().extract_text_from_file_bytes(b"%PDF fake", "intro.pdf")

    assert "第一页 产品介绍" in text
    assert "核心能力" in text
    assert "客户案例" in text
    assert "\n\n\n" not in text
