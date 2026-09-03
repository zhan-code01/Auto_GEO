"""deploy_service 单测。

纯单元测试，通过 mock 屏蔽真实 SFTP / OSS / 网络访问。
覆盖：目录名兜底、site_id 后缀、OSS 元数据(inline/无默认 ACL)、_verify_url 非阻断语义。
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.services.deploy_service import DeployError, DeployService


# ==================== fixtures ====================

@pytest.fixture
def service():
    return DeployService()


@pytest.fixture
def fake_site(tmp_path):
    """构造一个假站点目录：含 index.html + 一个 css + 一张图。返回 (site_id, path)。"""
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    site_id = "abcd1234efgh5678"
    site_path = sites_dir / site_id
    site_path.mkdir()
    (site_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (site_path / "style.css").write_text("body{}", encoding="utf-8")
    (site_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    # DeployService.sites_dir 默认指向 <repo>/backend/static/sites，这里重定向到临时目录
    return site_id, sites_dir


# ==================== 目录名 / slug ====================

def test_sanitize_name_strips_unsafe(service):
    assert service._sanitize_name("Turbo Logistics!") == "turbo_logistics"
    assert service._sanitize_name("中文项目") == ""
    assert service._sanitize_name("") == ""
    assert service._sanitize_name(None) == ""


def test_make_folder_name_falls_back_to_site_id_for_non_ascii(service):
    # 全中文项目名 → slug 为空 → 回退 site_id[:8]，且永远带 site_id[:8] 后缀
    folder = service._make_folder_name("极速物流", "abcd1234efgh5678")
    assert folder == "abcd1234-abcd1234"  # slug 回退 + 后缀 都是 site_id[:8]


def test_make_folder_name_has_site_id_suffix(service):
    folder = service._make_folder_name("Turbo Logistics", "abcd1234efgh5678")
    assert folder == "turbo_logistics-abcd1234"
    # 后缀防重名覆盖
    folder2 = service._make_folder_name("Turbo Logistics", "99999999efgh5678")
    assert folder2 != folder


def test_make_folder_name_custom_slug_wins(service):
    # publish_slug 里的 "-" 会被 _sanitize_name 转成 "_"（只保留字母数字）
    folder = service._make_folder_name("Turbo Logistics", "abcd1234efgh5678", publish_slug="my-site")
    assert folder == "my_site-abcd1234"


# ==================== OSS 元数据（inline / ACL） ====================

def _make_site_under(svc, sites_dir, site_id):
    """把 DeployService 的 sites_dir 指向临时目录，并返回该 site 的 path。"""
    svc.sites_dir = sites_dir
    return sites_dir / site_id


def test_s3_sets_inline_and_no_default_acl(service, fake_site):
    site_id, sites_dir = fake_site
    service.sites_dir = sites_dir

    fake_s3 = MagicMock()
    extra_args_seen = []

    def _capture(*, Filename, Bucket, Key, ExtraArgs):
        extra_args_seen.append(ExtraArgs)

    fake_s3.upload_file.side_effect = _capture

    with patch("backend.services.deploy_service.boto3.client", return_value=fake_s3):
        result = service.deploy_s3(
            site_id=site_id,
            endpoint="https://oss-cn-shenzhen.aliyuncs.com",
            bucket="autogeoext",
            access_key="ak",
            secret_key="sk",
        )

    # 每个对象都设 inline，且默认不传 ACL
    assert len(extra_args_seen) == 3
    for ea in extra_args_seen:
        assert ea["ContentDisposition"] == "inline"
        assert "ACL" not in ea
    # html/css 有 charset，svg 用 image 类型
    html_ea = next(ea for ea in extra_args_seen if ea["ContentType"].startswith("text/html"))
    assert "charset=utf-8" in html_ea["ContentType"]
    # 验证 URL 用了 virtual-hosted 形式
    assert result["url"] == "https://autogeoext.oss-cn-shenzhen.aliyuncs.com/index.html"
    assert result["uploaded_files"] == 3


def test_s3_never_sets_object_acl(service, fake_site):
    """对象 ACL 选项已移除：永远不传 ACL，只设 inline + 正确 Content-Type。"""
    site_id, sites_dir = fake_site
    service.sites_dir = sites_dir

    fake_s3 = MagicMock()
    extra_args_seen = []
    fake_s3.upload_file.side_effect = lambda *, Filename, Bucket, Key, ExtraArgs: extra_args_seen.append(ExtraArgs)

    with patch("backend.services.deploy_service.boto3.client", return_value=fake_s3):
        service.deploy_s3(
            site_id=site_id,
            endpoint="https://oss-cn-shenzhen.aliyuncs.com",
            bucket="autogeoext",
            access_key="ak",
            secret_key="sk",
        )

    for ea in extra_args_seen:
        assert ea["ContentDisposition"] == "inline"
        assert "ACL" not in ea


def test_s3_public_base_url_overrides_default_url(service, fake_site):
    site_id, sites_dir = fake_site
    service.sites_dir = sites_dir
    fake_s3 = MagicMock()

    with patch("backend.services.deploy_service.boto3.client", return_value=fake_s3):
        result = service.deploy_s3(
            site_id=site_id,
            endpoint="https://oss-cn-shenzhen.aliyuncs.com",
            bucket="autogeoext",
            access_key="ak",
            secret_key="sk",
            public_base_url="https://www.example.com",
        )
    assert result["url"] == "https://www.example.com/index.html"


# ==================== _verify_url 非阻断语义 ====================

def test_verify_url_returns_ok_on_200_html(service):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "text/html; charset=utf-8", "content-disposition": "inline"}
    with patch("backend.services.deploy_service.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = fake_resp
        out = service._verify_url("https://x/index.html")
    assert out["ok"] is True
    assert out["warning"] is None


def test_verify_url_attachment_header(service):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "text/html", "content-disposition": "attachment; filename=index.html"}
    with patch("backend.services.deploy_service.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = fake_resp
        out = service._verify_url("https://x/index.html")
    assert out["ok"] is False
    assert "attachment" in out["warning"]
    # 普通 Nginx 域名 → 建议改 inline
    assert "inline" in out["suggestion"]


def test_verify_url_attachment_on_oss_default_domain(service):
    """OSS 默认域名被强制加 attachment：提示应指向「绑定自定义域名」，而非改 Nginx。"""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "text/html", "content-disposition": "attachment; filename=index.html"}
    with patch("backend.services.deploy_service.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = fake_resp
        out = service._verify_url("https://bucket.oss-cn-shenzhen.aliyuncs.com/index.html")
    assert out["ok"] is False
    assert "自定义域名" in out["suggestion"]
    assert "inline" not in out["suggestion"]


def test_verify_url_non_html_content_type(service):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {"content-type": "application/octet-stream"}
    with patch("backend.services.deploy_service.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = fake_resp
        out = service._verify_url("https://x/index.html")
    assert out["ok"] is False
    assert "octet-stream" in out["warning"]


def test_verify_url_network_error_does_not_raise(service):
    """超时/连接失败必须降级为 warning，绝不能抛异常（否则会误阻断返回 URL）。"""
    with patch("backend.services.deploy_service.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        out = service._verify_url("https://x/index.html")
    assert out["ok"] is False
    assert out["warning"]  # 有提示文字
    assert out["suggestion"]  # 有修复建议


# ==================== site 不存在 → DeployError ====================

def test_missing_site_raises_deploy_error_404(service, tmp_path):
    service.sites_dir = tmp_path  # 空目录
    with pytest.raises(DeployError) as exc_info:
        service.deploy_s3(
            site_id="not-exist",
            endpoint="https://oss.example.com",
            bucket="b",
            access_key="ak",
            secret_key="sk",
        )
    assert exc_info.value.code == "SITE_NOT_FOUND"
    assert exc_info.value.status == 404
