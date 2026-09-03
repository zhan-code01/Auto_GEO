import pytest

from backend.services.article_image_service import ArticleImageService, ImageSlot


@pytest.mark.asyncio
async def test_process_article_images_keeps_remote_url_without_downloading(monkeypatch):
    service = ArticleImageService()

    async def fail_if_downloaded(_url):
        raise AssertionError("article generation must not download images")

    monkeypatch.setattr(service, "_download_image", fail_if_downloaded)
    content = "# 标题\n\n{{IMAGE_SLOT:1|hero|智能制造工厂}}\n\n正文"

    result = await service.process_article_images(
        content,
        article_id=123,
        keyword="制造业MES系统",
        title="制造企业生产排程优化",
    )

    assert "https://loremflickr.com/1200/675/" in result
    assert "lock=" in result
    assert "/static/uploads/article-images/" not in result


def test_industry_tokens_use_full_phrase_matching():
    service = ArticleImageService()

    tokens = service._get_industry_tokens("制造业MES系统")

    assert "manufacturing" in tokens
    assert "factory" in tokens
    assert "ready-meal" not in tokens


def test_loremflickr_query_keeps_industry_context_before_generic_saas_words():
    service = ArticleImageService()
    slot = ImageSlot(
        index=1,
        kind="hero",
        intent=service._normalize_intent(
            "生产车间数据看板",
            keyword="制造业MES系统",
            title="制造企业生产排程优化",
        ),
    )

    url = service._image_url(slot, article_id=123, keyword="制造业MES系统", title="制造企业生产排程优化", attempt=0)

    assert "loremflickr.com/1200/675/" in url
    assert "manufacturing" in url
    assert "factory" in url
    assert "lock=" in url


def test_loremflickr_query_uses_product_packaging_context():
    service = ArticleImageService()
    slot = ImageSlot(
        index=1,
        kind="section",
        intent=service._normalize_intent(
            "canned foie gras food packaging metal can",
            keyword="鹅肝罐头能保存多久",
            title="鹅肝罐头能保存多久？百盛千鲜专业解答",
        ),
    )

    url = service._image_url(
        slot,
        article_id=999,
        keyword="鹅肝罐头能保存多久",
        title="鹅肝罐头能保存多久？百盛千鲜专业解答",
        attempt=0,
    )

    assert "food,restaurant,chef,dish,kitchen" in url
    assert "professional,business,corporate" not in url
