"""site_builder 按用户隔离的单元测试。

纯单测：mock 掉 db / generator / deployer，不依赖真实数据库或运行的服务器。
覆盖隔离的"编排逻辑"——build 的 upsert 复用、deploy 的归属校验（403/404/admin 分支）。
（user_id 的真实自动填充由 main.py 注册的 auto_user_id 事件保障，属集成层，此处不重复测。）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.site_builder import DeployRequest, SiteBuildRequest, build_new_site, deploy_site


# ==================== fixtures ====================

def _user(uid, role="user"):
    return SimpleNamespace(id=uid, role=role)


def _req_build(name="我的站点"):
    return SiteBuildRequest(name=name, config={"company_name": name}, template_id="corporate")


def _req_deploy(site_id, method="sftp"):
    return DeployRequest(
        site_id=site_id, project_name="p", method=method,
        sftp_host="1.2.3.4", sftp_port=22, sftp_user="u", sftp_pass="pw",
        sftp_path="/var/www/html", public_base_url="https://e.com",
    )


def _req_deploy_with_private_key(site_id):
    return DeployRequest(
        site_id=site_id,
        project_name="p",
        method="sftp",
        sftp_host="1.2.3.4",
        sftp_port=22,
        sftp_user="u",
        sftp_auth_type="private_key",
        sftp_private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        sftp_path="/var/www/html",
        public_base_url="https://e.com",
    )


def _mock_db(first_result):
    """构造一个 db，其 query(...).filter(...).first() 返回 first_result。"""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = first_result
    return db


# ==================== build：upsert 复用 / 新建 ====================

def test_build_reuses_existing_siteproject_for_same_name():
    """同名站点复用同一 site_id（防 debounce 频繁触发导致记录膨胀）。"""
    existing = SimpleNamespace(site_id="existing-id-1234", name="我的站点")
    db = _mock_db(first_result=existing)

    fake_generator = MagicMock()
    fake_generator.generate_site.return_value = {
        "local_path": "/tmp/x", "preview_url": "/static/sites/existing-id-1234/index.html"
    }

    with patch("backend.api.site_builder.generator", fake_generator):
        result = build_new_site(_req_build("我的站点"), db=db, current_user=_user(1))

    # 复用既有 site_id，不新建（db.add 不应被调用）
    assert result["data"]["site_id"] == "existing-id-1234"
    db.add.assert_not_called()
    # generator 用复用的 site_id 渲染（覆盖同一静态目录）
    fake_generator.generate_site.assert_called_once()
    assert fake_generator.generate_site.call_args.kwargs.get("site_id", fake_generator.generate_site.call_args.args[0]) == "existing-id-1234"
    db.commit.assert_called_once()


def test_build_creates_new_siteproject_when_none_exists():
    """首次构建：新建 SiteProject 并 db.add。"""
    db = _mock_db(first_result=None)

    fake_generator = MagicMock()
    fake_generator.generate_site.return_value = {"local_path": "/tmp/y", "preview_url": "/static/sites/z/index.html"}

    with patch("backend.api.site_builder.generator", fake_generator):
        result = build_new_site(_req_build("全新站点"), db=db, current_user=_user(2))

    db.add.assert_called_once()  # 新建了记录
    added = db.add.call_args.args[0]
    assert added.name == "全新站点"
    assert added.site_id  # 生成了 site_id
    assert result["data"]["site_id"] == added.site_id


# ==================== deploy：归属校验 ====================

def test_deploy_returns_404_when_site_not_found():
    """site_id 不属于任何记录 → 404 SITE_NOT_FOUND。"""
    db = _mock_db(first_result=None)
    with pytest.raises(HTTPException) as exc:
        deploy_site(_req_deploy("unknown"), db=db, current_user=_user(1))
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "SITE_NOT_FOUND"


def test_deploy_forbidden_for_non_owner():
    """非归属用户 deploy 他人站点 → require_owner 抛 403。"""
    proj = SimpleNamespace(site_id="a-site", user_id=1)  # 属于 user 1
    db = _mock_db(first_result=proj)

    with pytest.raises(HTTPException) as exc:
        deploy_site(_req_deploy("a-site"), db=db, current_user=_user(2, role="user"))
    assert exc.value.status_code == 403


def test_deploy_admin_bypasses_ownership():
    """admin 可发布任意 site_id → 放行进入 deployer。"""
    proj = SimpleNamespace(site_id="a-site", user_id=1)  # 属于 user 1
    db = _mock_db(first_result=proj)

    fake_deployer = MagicMock()
    fake_deployer.deploy_sftp.return_value = {"status": "success", "url": "https://e.com/x/index.html"}

    with patch("backend.api.site_builder.deployer", fake_deployer):
        result = deploy_site(_req_deploy("a-site"), db=db, current_user=_user(99, role="admin"))

    assert result["code"] == 200
    fake_deployer.deploy_sftp.assert_called_once()


def test_deploy_owner_allowed():
    """归属用户 deploy 自己的站点 → 放行进入 deployer。"""
    proj = SimpleNamespace(site_id="a-site", user_id=5)
    db = _mock_db(first_result=proj)

    fake_deployer = MagicMock()
    fake_deployer.deploy_sftp.return_value = {"status": "success", "url": "https://e.com/x/index.html"}

    with patch("backend.api.site_builder.deployer", fake_deployer):
        result = deploy_site(_req_deploy("a-site"), db=db, current_user=_user(5))

    assert result["code"] == 200
    fake_deployer.deploy_sftp.assert_called_once()


def test_deploy_private_key_does_not_require_password():
    """PEM 私钥方式不要求同时填写密码。"""
    proj = SimpleNamespace(site_id="a-site", user_id=5)
    db = _mock_db(first_result=proj)

    fake_deployer = MagicMock()
    fake_deployer.deploy_sftp.return_value = {"status": "success", "url": "https://e.com/x/index.html"}

    with patch("backend.api.site_builder.deployer", fake_deployer):
        result = deploy_site(_req_deploy_with_private_key("a-site"), db=db, current_user=_user(5))

    assert result["code"] == 200
    kwargs = fake_deployer.deploy_sftp.call_args.kwargs
    assert kwargs["auth_type"] == "private_key"
    assert kwargs["password"] is None
    assert kwargs["private_key"].startswith("-----BEGIN")


def test_deploy_private_key_requires_key_content():
    """选择 PEM 私钥方式但未提供私钥内容 → 提示缺少 PEM 私钥。"""
    proj = SimpleNamespace(site_id="a-site", user_id=5)
    db = _mock_db(first_result=proj)
    req = _req_deploy_with_private_key("a-site")
    req.sftp_private_key = ""

    with pytest.raises(HTTPException) as exc:
        deploy_site(req, db=db, current_user=_user(5))

    assert exc.value.status_code == 400
    assert "PEM 私钥" in exc.value.detail["message"]
