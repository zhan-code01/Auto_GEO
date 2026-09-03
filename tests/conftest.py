# -*- coding: utf-8 -*-
"""
Pytest配置和Fixtures
我用pytest，简洁好用的测试框架！
"""

import sys
import os
import time
import subprocess
import pytest
import requests
from pathlib import Path

# 设置UTF-8编码输出（Windows兼容）
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.database import SessionLocal
from backend.database.models import (
    Account, PublishRecord, Project, Keyword, ReferenceArticle,
    IndexCheckRecord, GeoArticle, QuestionVariant
)
from backend.scripts.schema_utils import ensure_schema_ready


# ==================== 配置 ====================
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8001
FRONTEND_HOST = "127.0.0.1"
FRONTEND_PORT = 5173

BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
FRONTEND_URL = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}"

# Mock模式环境变量
IS_MOCK = os.getenv("REAL_AI", "false").lower() != "true"
ALLOW_DEV_DB_TEST_CLEAN = os.getenv("AUTOGEO_ALLOW_DEV_DB_TEST_CLEAN", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _assert_safe_test_database(db):
    """Prevent pytest cleanup from wiping a developer/production database."""
    bind = db.get_bind()
    db_name = getattr(bind.url, "database", "") if bind is not None else ""
    if ALLOW_DEV_DB_TEST_CLEAN or "test" in (db_name or "").lower():
        return
    raise RuntimeError(
        "Refusing to run destructive pytest database cleanup against "
        f"database '{db_name}'. Use a dedicated test database, or set "
        "AUTOGEO_ALLOW_DEV_DB_TEST_CLEAN=true only if you intentionally want "
        "tests to delete data from this database."
    )


# ==================== 进程管理 ====================
class ProcessManager:
    """管理测试期间启动的子进程"""

    def __init__(self):
        self.processes = []

    def add(self, proc):
        """添加进程"""
        self.processes.append(proc)

    def cleanup(self):
        """清理所有进程"""
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except:
                    proc.kill()
        self.processes.clear()


process_manager = ProcessManager()


# ==================== Fixtures ====================

@pytest.fixture(scope="session")
def db():
    """数据库会话Fixture"""
    ensure_schema_ready()
    db = SessionLocal()
    _assert_safe_test_database(db)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def clean_db(db):
    """每个测试后清理数据库"""
    yield db
    # 清理测试数据（按依赖顺序逆序删除）
    db.query(PublishRecord).delete()
    db.query(GeoArticle).delete()
    db.query(IndexCheckRecord).delete()
    db.query(QuestionVariant).delete()
    db.query(Keyword).delete()
    db.query(Project).delete()
    db.query(Account).delete()
    db.query(ReferenceArticle).delete()
    db.commit()


@pytest.fixture(scope="session")
def backend_server():
    """启动后端服务器"""
    print("\n[INFO] 正在启动后端服务器...")

    # 启动后端
    backend_cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        f"--host={BACKEND_HOST}",
        f"--port={BACKEND_PORT}",
        "--log-level=warning"
    ]
    backend_proc = subprocess.Popen(
        backend_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(project_root)
    )
    process_manager.add(backend_proc)

    # 等待后端启动
    for i in range(30):
        try:
            resp = requests.get(f"{BACKEND_URL}/api/health", timeout=2)
            if resp.status_code == 200:
                print(f"[OK] 后端服务器启动成功 ({BACKEND_URL})")
                break
        except:
            time.sleep(1)
    else:
        raise RuntimeError("！后端服务器启动超时！")

    yield BACKEND_URL

    # 清理
    backend_proc.terminate()


@pytest.fixture(scope="session")
def frontend_server():
    """启动前端开发服务器"""
    print("\n[INFO] 正在启动前端服务器...")

    # 启动前端
    frontend_cmd = ["npm", "run", "dev", "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT)]
    frontend_proc = subprocess.Popen(
        frontend_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(project_root / "fronted"),
        shell=True
    )
    process_manager.add(frontend_proc)

    # 等待前端启动
    for i in range(60):  # Vite启动比较慢
        try:
            resp = requests.get(f"{FRONTEND_URL}/", timeout=2)
            if resp.status_code == 200:
                print(f"[OK] 前端服务器启动成功 ({FRONTEND_URL})")
                break
        except:
            time.sleep(1)
    else:
        raise RuntimeError("！前端服务器启动超时！")

    yield FRONTEND_URL

    # 清理
    frontend_proc.terminate()


@pytest.fixture(scope="session")
def app_servers(backend_server, frontend_server):
    """同时启动前后端服务器"""
    return {
        "backend": backend_server,
        "frontend": frontend_server
    }


@pytest.fixture(scope="function")
def test_account(clean_db):
    """创建测试账号"""
    account = Account(
        platform="zhihu",
        account_name="测试账号",
        username="test_user",
        status=1
    )
    clean_db.add(account)
    clean_db.commit()
    clean_db.refresh(account)
    return account


@pytest.fixture(scope="function")
def test_project(clean_db):
    """创建测试项目"""
    project = Project(
        name="自动化测试项目",
        company_name="测试公司",
        description="用于自动化测试",
        status=1
    )
    clean_db.add(project)
    clean_db.commit()
    clean_db.refresh(project)
    return project


@pytest.fixture(scope="function")
def test_keyword(clean_db, test_project):
    """创建测试关键词"""
    keyword = Keyword(
        project_id=test_project.id,
        keyword="SEO优化",
        difficulty_score=50,
        status="active"
    )
    clean_db.add(keyword)
    clean_db.commit()
    clean_db.refresh(keyword)
    return keyword




# ==================== Hooks ====================

def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--real-env",
        action="store_true",
        default=False,
        help="运行真实环境测试（会打开浏览器进行真实抓取）"
    )


def pytest_configure(config):
    """Pytest配置"""
    config.addinivalue_line("markers", "geo: GEO关键词模块测试")
    config.addinivalue_line("markers", "monitor: AI检测监控模块测试")
    config.addinivalue_line("markers", "publish: 文章发布模块测试")
    config.addinivalue_line("markers", "slow: 慢速测试")
    config.addinivalue_line("markers", "collection: 爆火文章收集模块测试")
    config.addinivalue_line("markers", "integration: 集成测试（需要启动服务器）")
    config.addinivalue_line("markers", "real_env: 真实环境测试（需要 --real-env 参数）")


def pytest_collection_modifyitems(config, items):
    """根据命令行选项跳过特定测试"""
    if not config.getoption("--real-env"):
        # 如果没有 --real-env 选项，跳过标记为 real_env 的测试
        skip_real_env = pytest.mark.skip(reason="需要添加 --real-env 参数才能运行真实环境测试")
        for item in items:
            if "real_env" in item.keywords:
                item.add_marker(skip_real_env)


def pytest_sessionstart(session):
    """测试会话开始"""
    print("\n" + "="*50)
    print("[AutoGeo] 自动化测试开始")
    print("="*50)
    print(f"Mock模式: {'开启' if IS_MOCK else '关闭'}")
    print("="*50)


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束"""
    # 清理进程
    process_manager.cleanup()

    print("\n" + "="*50)
    print(f"[AutoGeo] 测试结束，退出码: {exitstatus}")
    print("="*50)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """每个测试的钩子，用于截图和日志"""
    outcome = yield
    report = outcome.get_result()

    # 测试失败时的处理
    if report.when == "call" and report.failed:
        # 这里可以添加截图、保存日志等逻辑
        pass
