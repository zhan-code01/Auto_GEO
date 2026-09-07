# -*- coding: utf-8 -*-
"""
AutoGeo 后端主程序
"""

import sys
import os

# ========== Windows 控制台 UTF-8 修复（必须在最前面！） ==========
# 解决 Windows GBK/GB2312 控制台输出中文乱码问题
if sys.platform == "win32":
    import io

    if getattr(sys.stdout, "buffer", None):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if getattr(sys.stderr, "buffer", None):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
import uuid

from backend.utils.asyncio_compat import configure_windows_asyncio_policy, install_asyncio_exception_filter

configure_windows_asyncio_policy()

# ==================== 集中式日志初始化（必须尽早，早于任何会触发日志的导入） ====================
import asyncio  # noqa: E402 (socket_log_sink 依赖)
from loguru import logger  # noqa: E402

from backend.log_setup import setup_logging  # noqa: E402


def socket_log_sink(message):
    """
    Loguru 拦截器：将每一条日志通过 WebSocket 广播出去（前端实时日志面板）
    """
    try:
        record = message.record
        log_payload = {
            "time": record["time"].strftime("%H:%M:%S"),
            "level": record["level"].name,
            "module": record["extra"].get("module", "系统"),
            "message": record["message"],
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast(log_payload))
        except RuntimeError:
            pass
        except Exception:
            pass
    except Exception:
        pass


# 挂载：控制台 + 按日期命名的本地日志文件（只保留最近 3 天）+ WebSocket 实时广播
setup_logging(socket_sink=socket_log_sink)

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# 导入配置和数据库
from backend.config import (
    APP_NAME,
    APP_VERSION,
    DEBUG,
    HOST,
    PORT,
    RELOAD,
    CORS_ORIGINS,
    CORS_ALLOW_ORIGIN_REGEX,
    PLATFORMS,
)
from backend.config import DATABASE_URL, get_database_type
from backend.database import SessionLocal

# 全局认证中间件 + 用户数据隔离 + 访问日志
from backend.middleware.auth_middleware import AuthMiddleware
from backend.middleware.user_isolation import register_model_for_auto_user_id
from backend.middleware.access_log import AccessLogMiddleware

# 导入所有 API 路由模块
import backend.api.account as account
import backend.api.article as article
import backend.api.publish as publish
import backend.api.keywords as keywords
import backend.api.geo as geo
import backend.api.index_check as index_check
import backend.api.reports as reports
import backend.api.notifications as notifications
import backend.api.scheduler as scheduler
import backend.api.knowledge as knowledge
import backend.api.auth as auth
import backend.api.article_collection as article_collection
import backend.api.site_builder as site_builder
import backend.api.upload as upload
import backend.api.client as client  # 客户管理
import backend.api.auto_publish as auto_publish  # 自动发布任务
import backend.api.client_device as client_device  # 本地客户端设备
import backend.api.client_account as client_account  # 本地客户端账号绑定
import backend.api.client_geo_evaluation as client_geo_evaluation  # 本地客户端GEO测评
import backend.api.client_publish as client_publish  # 本地客户端发布任务
import backend.api.client_download as client_download  # 客户端安装包下载
import backend.api.browser as browser  # 本地浏览器桥接
import backend.api.deployment as deployment  # 部署配置
import backend.api.user as user  # 用户管理
import backend.api.admin as admin  # 管理员配置
import backend.api.feishu as feishu  # 飞书机器人
import backend.api.integrations as integrations  # 外部 Agent 集成入口
import backend.api.geo_evaluation as geo_evaluation  # GEO 五指标测评
import backend.api.smart_articles as smart_articles  # 智能文章生成
import backend.api.agent_v2 as agent_v2  # 智能体 V2（SSE 流式）

# 导入服务组件
from backend.services.websocket_manager import ws_manager
from backend.services.scheduler_service import get_scheduler_service
from backend.services.playwright_mgr import playwright_mgr
from backend.services.playwright.publishers import register_publishers


# ==================== 日志初始化已完成（见文件顶部 setup_logging） ====================


# ==================== 应用生命周期管理 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    install_asyncio_exception_filter(asyncio.get_running_loop())
    # 所有模块导入完成后，重新断言 stdlib logging -> loguru 桥接（清除 basicConfig 残留）
    from backend.log_setup import reinstall_stdlib_bridge

    reinstall_stdlib_bridge()
    # ---------------- 启动阶段 ----------------
    logger.info(f"🚀 {APP_NAME} v{APP_VERSION} 正在启动...")

    # 1. Database schema is PostgreSQL-only and managed by Alembic.
    try:
        if not DATABASE_URL.lower().startswith(("postgresql://", "postgresql+")):
            raise RuntimeError("Only PostgreSQL DATABASE_URL values are supported.")
        logger.info("PostgreSQL mode: schema is managed by Alembic")
        logger.success("Database startup check complete")
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")
        raise

    # 1.5 注册用户数据隔离 —— 自动为新记录填充 user_id
    try:
        from backend.database.models import (
            GeoArticle,
            Project,
            SiteProject,
            Client,
            KnowledgeCategory,
            AutoPublishTask,
            SmartArticleBatch,
            SmartArticleJob,
            SmartArticleQuestion,
        )

        register_model_for_auto_user_id(GeoArticle)
        register_model_for_auto_user_id(Project)
        register_model_for_auto_user_id(SiteProject)
        register_model_for_auto_user_id(Client)
        register_model_for_auto_user_id(KnowledgeCategory)
        register_model_for_auto_user_id(AutoPublishTask)
        register_model_for_auto_user_id(SmartArticleBatch)
        register_model_for_auto_user_id(SmartArticleJob)
        register_model_for_auto_user_id(SmartArticleQuestion)
        logger.success("✅ 用户数据隔离已启用")
    except Exception as e:
        logger.error(f"❌ 用户数据隔离注册失败: {e}")

    # 2. 注入全局 WebSocket 管理器
    account.set_ws_manager(ws_manager)
    publish.set_ws_manager(ws_manager)
    notifications.set_ws_callback(ws_manager.broadcast)

    # 3. 初始化 Playwright 管理器
    playwright_mgr.set_db_factory(SessionLocal)
    playwright_mgr.set_ws_callback(ws_manager.broadcast)
    logger.bind(module="发布器").success("发布器已配置")

    # 4. 启动定时任务引擎
    scheduler_instance = get_scheduler_service()
    scheduler_instance.set_db_factory(SessionLocal)
    scheduler_instance.start()
    logger.bind(module="调度中心").success("自动化任务引擎已启动")

    # 5. 注册平台发布适配器
    register_publishers(PLATFORMS)
    logger.bind(module="发布器").success(
        f"已注册 {len([k for k in PLATFORMS.keys() if k in ['zhihu', 'baijiahao', 'sohu', 'toutiao', 'xiaohongshu', 'douyin']])} 个平台发布器"
    )

    # 6. 初始化飞书机器人客户端
    from backend.services.feishu_client import get_feishu_client

    feishu_client = get_feishu_client()
    if feishu_client.is_configured:
        logger.bind(module="飞书机器人").success("飞书机器人已就绪")
    else:
        logger.bind(module="飞书机器人").info("飞书机器人未配置，跳过初始化")

    yield

    # ---------------- 关闭阶段 ----------------
    logger.info("正在关闭服务，释放资源...")
    scheduler_instance.stop()
    await playwright_mgr.stop()
    await feishu_client.close()
    logger.info("服务已安全关闭")


# ==================== 创建应用实例 ====================
app = FastAPI(title=APP_NAME, version=APP_VERSION, debug=DEBUG, lifespan=lifespan)

# 全局认证中间件 —— 强制 /api/* 请求携带有效 JWT
# 白名单：/api/users/register, /api/users/login, /api/health, /api/platforms 等
# 注意：必须先于 CORS 注册（FastAPI 中后注册的在外层，CORS 必须在最外层处理 OPTIONS 预检）
app.add_middleware(AuthMiddleware)

# 跨域中间件（最外层，确保 OPTIONS 预检请求在认证之前被处理）
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 访问日志中间件（最外层：记录所有 HTTP 请求，含 CORS 预检与认证失败）
app.add_middleware(AccessLogMiddleware)


# ==================== 静态资源挂载 ====================
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")

if not os.path.exists(static_dir):
    logger.info(f"正在创建静态目录: {static_dir}")
    os.makedirs(static_dir)

if not os.path.exists(os.path.join(static_dir, "uploads")):
    os.makedirs(os.path.join(static_dir, "uploads"))

if not os.path.exists(os.path.join(static_dir, "sites")):
    os.makedirs(os.path.join(static_dir, "sites"))

app.mount("/static", StaticFiles(directory=static_dir), name="static")
logger.success(f"✅ 静态资源已挂载: {static_dir}")


# ==================== 注册路由 ====================
app.include_router(account.router)
app.include_router(article.router)
app.include_router(publish.router)
app.include_router(keywords.router)
app.include_router(geo.router)
app.include_router(index_check.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(scheduler.router)
app.include_router(knowledge.router)
app.include_router(upload.router)  # 文件上传
app.include_router(client.router)  # 客户管理
app.include_router(auth.router)
app.include_router(article_collection.router)
app.include_router(site_builder.router)
app.include_router(site_builder.router, prefix="/api")
app.include_router(auto_publish.router)  # 自动发布任务管理
app.include_router(client_device.router)  # 本地客户端设备注册与心跳
app.include_router(client_account.router)  # 本地客户端账号绑定
app.include_router(client_geo_evaluation.router)  # 本地客户端GEO测评任务
app.include_router(client_publish.router)  # 本地客户端领取并执行发布任务
app.include_router(client_download.router)  # 客户端安装包下载
app.include_router(browser.router)  # 本地浏览器桥接
app.include_router(deployment.router)  # 部署配置
app.include_router(user.router)  # 用户认证
app.include_router(admin.router)  # 管理员配置
app.include_router(feishu.router)  # 飞书机器人
app.include_router(integrations.router)  # 外部 Agent 集成入口
app.include_router(geo_evaluation.router)  # GEO 五指标测评后台智能对话
app.include_router(smart_articles.router)  # 智能文章生成
app.include_router(agent_v2.router)  # 智能体 V2（SSE 流式）


# ==================== WebSocket 端点 ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client_id: str = None, token: str = None):
    """WebSocket 端点。

    可选 token 参数：前端建立连接时带 JWT token，后端解析出 user_id，
    建立 user → client 映射，供 Agent V2 异步任务通知使用（ws_manager.notify_user）。
    若不带 token，则兼容老逻辑（仅按 client_id 索引）。
    """
    if not client_id:
        client_id = f"client_{uuid.uuid4().hex[:8]}"

    # 尝试从 token 解析 user_id
    user_id: int | None = None
    if token:
        try:
            from backend.api.user import decode_token

            payload = decode_token(token)
            if payload:
                user_id = payload.get("user_id")
        except Exception as e:
            logger.warning(f"[WebSocket] token 解析失败: {e}")

    await ws_manager.connect(websocket, client_id, user_id=user_id)
    await ws_manager.send_personal(
        {
            "time": "系统",
            "level": "SUCCESS",
            "module": "系统",
            "message": "实时监控链路已就绪",
        },
        client_id,
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 异常: {e}")
        ws_manager.disconnect(client_id)


# ==================== 基础健康检查 ====================
@app.get("/")
async def root():
    return {"app": APP_NAME, "version": APP_VERSION, "status": "running"}


@app.get("/api/health")
async def health():
    """增强健康检查端点，返回各服务连接状态"""
    import httpx

    health_status = {
        "status": "ok",
        "timestamp": None,
        "services": {
            "database": {"status": "unknown"},
            "ragflow": {"status": "unknown"},
        },
    }

    # 导入时间模块
    from datetime import datetime

    health_status["timestamp"] = datetime.now().isoformat()

    # 1. 数据库连接检测
    try:
        from backend.database import SessionLocal, get_engine_info

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        engine_info = get_engine_info()
        db_health = {"status": "connected", "type": engine_info.get("type", "unknown")}

        # 尝试获取 Alembic 当前版本（仅 PostgreSQL）
        if get_database_type() == "postgresql":
            try:
                from alembic.config import Config as AlembicConfig
                from alembic.script import ScriptDirectory

                alembic_cfg = AlembicConfig()
                alembic_cfg.set_main_option("script_location", "migrations")
                alembic_cfg.set_main_option(
                    "sqlalchemy.url",
                    str(engine_info.get("url", "")),
                )
                # 从数据库读取当前版本
                from backend.database import engine as db_engine
                from alembic.runtime.migration import MigrationContext

                with db_engine.connect() as conn:
                    context = MigrationContext.configure(conn)
                    db_health["alembic_revision"] = context.get_current_revision()
            except Exception:
                pass  # 非关键，获取失败不影响健康检查

        health_status["services"]["database"] = db_health
    except Exception as e:
        health_status["services"]["database"] = {"status": "error", "message": str(e)[:100]}
        health_status["status"] = "degraded"

    # 2. RAGFlow 连接检测
    try:
        from backend.config import RAGFLOW_BASE_URL, RAGFLOW_API_KEY

        if RAGFLOW_API_KEY and RAGFLOW_BASE_URL:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{RAGFLOW_BASE_URL}/api/v1/datasets", headers={"Authorization": f"Bearer {RAGFLOW_API_KEY}"}
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 0:
                        health_status["services"]["ragflow"] = {"status": "connected"}
                    else:
                        health_status["services"]["ragflow"] = {
                            "status": "error",
                            "message": result.get("message", "unknown error")[:100],
                        }
                else:
                    health_status["services"]["ragflow"] = {"status": "error", "code": response.status_code}
        else:
            health_status["services"]["ragflow"] = {"status": "not_configured"}
    except Exception as e:
        health_status["services"]["ragflow"] = {"status": "error", "message": str(e)[:100]}
        health_status["status"] = "degraded"

    return health_status


@app.get("/api/platforms")
async def get_platforms():
    return {"platforms": list(PLATFORMS.values())}


# ==================== 全局异常处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception(f"未处理的异常: {exc}")
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"success": False, "message": f"服务器内部错误: {str(exc)}", "detail": str(exc)},
    )


# ==================== 启动脚本 ====================
if __name__ == "__main__":
    # 艹！Windows下必须用ProactorEventLoop才能支持Playwright的subprocess
    # SelectorEventLoop在Windows下不支持subprocess，会导致NotImplementedError
    if sys.platform == "win32":
        configure_windows_asyncio_policy()

    logger.info(f"正在启动 {APP_NAME} v{APP_VERSION}...")
    logger.info(f"服务地址: http://{HOST}:{PORT}")

    if RELOAD:
        # log_config=None：uvicorn 日志统一走 loguru 桥接；access_log=False：访问日志由 AccessLogMiddleware 统一记录
        uvicorn.run(
            "backend.main:app", host=HOST, port=PORT, reload=True, log_level="info", access_log=False, log_config=None
        )
    else:
        uvicorn.run(app, host=HOST, port=PORT, reload=False, log_level="info", access_log=False, log_config=None)
