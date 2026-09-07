# -*- coding: utf-8 -*-
"""
Playwright浏览器管理器 - 简化版
直接拉起本地浏览器进行授权，适用于本地测试和桌面客户端
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from backend.utils.asyncio_compat import configure_windows_asyncio_policy

# ==================== Windows asyncio subprocess 兼容性修复 ====================
if sys.platform == "win32":
    try:
        configure_windows_asyncio_policy()
    except AttributeError:
        import warnings

        warnings.warn("Python版本过低，Windows ProactorEventLoopPolicy不可用，Playwright可能会失败")
# ==================== 修复结束 ====================

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger
from sqlalchemy.orm import Session

from backend.config import (
    BROWSER_TYPE,
    BROWSER_ARGS,
    DEFAULT_USER_AGENT,
    PLATFORMS,
)
from backend.services.crypto import encrypt_cookies, encrypt_storage_state, decrypt_cookies, decrypt_storage_state
from backend.services.playwright.session_state import normalize_platform_storage_state

# 发布器注册表
from backend.services.playwright.publishers.base import registry


class AuthTask:
    """授权任务模型"""

    def __init__(
        self,
        platform: str,
        account_id: Optional[int] = None,
        account_name: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        self.task_id = str(uuid.uuid4())
        self.platform = platform
        self.account_id = account_id
        self.account_name = account_name
        self.user_id = user_id
        self.status = "pending"  # pending, running, success, failed, timeout
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cookies: List[Dict] = []
        self.storage_state: Dict = {}
        self.error_message: Optional[str] = None
        self.created_at = datetime.now()
        self.created_account_id: Optional[int] = None


class PlaywrightManager:
    """
    Playwright 管理器 (单例模式)
    简化版：直接拉起本地浏览器，无需CDP/noVNC
    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._auth_tasks: Dict[str, AuthTask] = {}
        self._contexts: Dict[str, BrowserContext] = {}
        self._is_running = False
        self._db_factory: Optional[Callable] = None
        self._ws_callback: Optional[Callable] = None
        self._last_launch_info: Dict[str, Any] = {"is_running": False}

    def set_db_factory(self, db_factory: Callable):
        """设置数据库会话工厂"""
        self._db_factory = db_factory

    def set_ws_callback(self, callback: Callable):
        """设置 WebSocket 通知回调"""
        self._ws_callback = callback

    def _get_db(self) -> Optional[Session]:
        """获取数据库会话"""
        if self._db_factory:
            try:
                db_obj = self._db_factory()
                if hasattr(db_obj, "__next__"):
                    return next(db_obj)
                return db_obj
            except Exception as e:
                logger.error(f"获取数据库会话失败: {e}")
                return None
        return None

    async def start(self):
        """启动浏览器服务"""
        if self._is_running and self._browser:
            try:
                if self._browser.is_connected():
                    return
            except Exception:
                pass
            # browser 已断连，重置状态
            logger.warning("⚠️ 浏览器已断开，重新启动...")
            self._is_running = False
            self._browser = None

        logger.info("🚀 正在启动 Playwright 浏览器...")
        await self._start_browser()

    async def _start_browser(self):
        """直接启动本地浏览器（headless=False，用户可见）"""
        # Windows 下设置事件循环
        if sys.platform == "win32":
            try:
                configure_windows_asyncio_policy()
            except Exception as e:
                logger.error(f"设置事件循环策略失败: {e}")

        self._playwright = await async_playwright().start()

        # 查找本地 Chrome
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]

        if sys.platform == "darwin":
            chrome_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]

        executable_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                executable_path = path
                logger.info(f"✅ 找到本地 Chrome: {path}")
                break

        # 构建启动参数
        args = list(BROWSER_ARGS)

        # 关键：headless=False 让用户能看到浏览器窗口
        launch_options = {
            "headless": False,
            "args": args,
        }

        if executable_path:
            launch_options["executable_path"] = executable_path

        try:
            self._browser = await self._playwright[BROWSER_TYPE].launch(**launch_options)
            self._is_running = True
            self._last_launch_info = {
                "is_running": True,
                "mode": "local",
                "headless": False,
            }
            logger.success("✅ Playwright 浏览器已就绪（用户可见窗口）")
        except Exception as e:
            logger.error(f"❌ 浏览器启动失败: {e}")
            raise e

    async def stop(self):
        """停止浏览器服务"""
        if not self._is_running:
            return

        for context in self._contexts.values():
            await context.close()
        self._contexts.clear()

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self._is_running = False
        self._last_launch_info["is_running"] = False
        logger.info("🛑 Playwright 浏览器服务已停止")

    # ==================== 授权相关 ====================

    async def create_auth_task(
        self,
        platform: str,
        account_id: Optional[int] = None,
        account_name: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> AuthTask:
        """
        创建授权任务：启动浏览器，打开登录页
        """
        logger.info(f"[Auth] 开始授权: platform={platform}, account_id={account_id}")

        # 清理过期任务
        await self._cleanup_expired_tasks(timeout_minutes=5)

        # 单任务锁
        running_tasks = [t for t in self._auth_tasks.values() if t.status in ("pending", "running")]
        if running_tasks:
            raise RuntimeError("已有授权任务在进行中，请等待完成后重试")

        await self.start()

        if platform not in PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        task = AuthTask(platform, account_id, account_name, user_id)
        self._auth_tasks[task.task_id] = task

        try:
            if not self._browser:
                raise RuntimeError("浏览器未启动")

            # 创建上下文
            context = await self._browser.new_context(
                no_viewport=True,
                user_agent=DEFAULT_USER_AGENT,
            )
            task.context = context

            # 注入确认授权函数
            async def confirm_auth_wrapper(task_id_from_browser: str) -> str:
                return await self._finalize_auth(task_id_from_browser)

            await context.expose_function("confirmAuth", confirm_auth_wrapper)

            # 打开登录页
            login_page = await context.new_page()
            task.page = login_page
            await login_page.bring_to_front()
            await login_page.goto(PLATFORMS[platform]["login_url"], wait_until="domcontentloaded")

            task.status = "running"
            logger.info(f"[Auth] 授权任务就绪: {task.task_id}")

            # 使用全局后台任务管理器启动轮询任务（不会被 SSE 流取消）
            from backend.services.background_task_manager import background_task_manager

            logger.info(f"[Auth] 启动轮询任务: {task.task_id}")

            # 直接创建任务，确保它能被调度
            import asyncio

            poll_task = asyncio.create_task(self._poll_login_status(task.task_id))
            logger.info(f"[Auth] 轮询任务已创建: {task.task_id}, task={poll_task}")

            # 同时注册到后台任务管理器（防止被取消）
            background_task_manager.register_task(f"auth_poll_{task.task_id}", poll_task)
            logger.info(f"[Auth] 全局后台轮询任务已注册: {task.task_id}")

            return task

        except Exception as e:
            logger.error(f"[Auth] 创建授权任务失败: {e}")
            task.status = "failed"
            task.error_message = str(e)
            await self.close_auth_task(task.task_id)
            raise

    def get_auth_task(self, task_id: str) -> Optional[AuthTask]:
        """获取授权任务"""
        return self._auth_tasks.get(task_id)

    async def _poll_login_status(self, task_id: str, check_interval: int = 3, max_wait: int = 300):
        """
        轮询检测登录状态，自动完成授权流程

        Args:
            task_id: 授权任务ID
            check_interval: 检查间隔（秒）
            max_wait: 最大等待时间（秒）
        """
        logger.info(f"[Auth] 轮询任务开始执行: {task_id}")
        task = self._auth_tasks.get(task_id)
        if not task:
            logger.warning(f"[Auth] 轮询任务不存在: {task_id}")
            return

        logger.info(f"[Auth] 开始轮询登录状态: {task_id}")
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            logger.debug(f"[Auth] 轮询检查 {task_id}: elapsed={elapsed}s")

            # 检查任务是否还存在
            task = self._auth_tasks.get(task_id)
            if not task or task.status in ("success", "failed"):
                logger.info(f"[Auth] 任务已结束或不存在: {task_id}")
                break

            # 检查页面是否还存在
            if not task.page or task.page.is_closed():
                logger.warning(f"[Auth] 页面已关闭: {task_id}")
                task.status = "failed"
                task.error_message = "用户关闭了浏览器"
                break

            # 检测是否有登录成功的 cookies
            try:
                storage_state = await task.context.storage_state()
                cookies = storage_state.get("cookies", [])
                logger.debug(f"[Auth] 检测到 {len(cookies)} 个 cookies: {task_id}")

                # 平台关键 Cookie 验证
                platform_checks = {
                    "zhihu": "z_c0|z_cari0",
                    "baijiahao": "BDUSS|BDUSS_BFESS|STOKEN|PTOKEN",
                    "toutiao": "sessionid|sid_tt",
                    "wenku": "BDUSS|STOKEN",
                    "tieba": "BDUSS|STOKEN|BDUSS_BFESS",
                    "penguin": "uin|skey|p_sktkt",
                    "weixin": "slave_userinfo|data_bizuin|pass_ticket|pt2gguin",
                    "wangyi": "NTES_SESS|S_INFO",
                    "sohu": "ppinf|pprdig",
                    "jianshu": "remember_user_token|_m7e_session",
                    "juejin": "sessionid|sessionid_ss|passport_csrf_token|sid_tt",
                    "zijie": "sessionid|sid_tt",
                    "xiaohongshu": "xhs_web_session|webid|web_session|webId",
                    "bilibili": "bili_jct|SESSDATA|DedeUserID|DedeUserID__ckMd5",
                    "douyin": "sessionid|sessionid_ss|sid_guard|sid_tt|uid_tt",
                    "kuaishou": "userId|token|kuaishou.server_st",
                    "doubao": "sessionid|s_v_web_id|passport_csrf_token",
                    "deepseek": "sessionid|ds_session|auth_token",
                    "qianwen": "cna|login_aliyunid|isg",
                }

                key_cookie_str = platform_checks.get(task.platform)
                has_auth = False

                if key_cookie_str:
                    required_keys = key_cookie_str.split("|")
                    cookie_names = [c["name"].lower() for c in cookies]
                    has_auth = any(k.lower() in cookie_names for k in required_keys)
                    logger.debug(
                        f"[Auth] 检查关键 Cookie: platform={task.platform}, required={required_keys}, found={[c['name'] for c in cookies if c['name'].lower() in [k.lower() for k in required_keys]]}"
                    )

                    # URL 负面排除：仍在登录页则拒绝
                    current_url = task.page.url if task.page else ""
                    url_lower = current_url.lower()
                    login_patterns = ["/login", "/signin", "/sign_in", "/passport", "/account/"]
                    if any(x in url_lower for x in login_patterns):
                        has_auth = False
                        logger.debug(f"[Auth] 仍在登录页: {current_url}")

                if has_auth:
                    logger.success(f"[Auth] 检测到登录成功: {task_id}，自动完成授权")
                    # 调用 finalize 完成授权
                    result = await self._finalize_auth(task_id)
                    result_json = json.loads(result)
                    if result_json.get("success"):
                        logger.success(f"[Auth] 授权完成: {task_id}")
                    else:
                        logger.error(f"[Auth] 授权失败: {task_id} - {result_json.get('message')}")
                    break

            except Exception as e:
                logger.warning(f"[Auth] 检测登录状态失败: {task_id} - {e}")
                continue

        # 超时处理
        if elapsed >= max_wait:
            task = self._auth_tasks.get(task_id)
            if task and task.status == "running":
                logger.warning(f"[Auth] 授权超时: {task_id}")
                task.status = "failed"
                task.error_message = "授权超时，请重试"
                await self.close_auth_task(task_id)

    def get_auth_diagnostics(self) -> Dict[str, Any]:
        """获取授权状态诊断"""
        active_tasks = [
            {
                "task_id": task.task_id,
                "platform": task.platform,
                "status": task.status,
                "created_at": task.created_at.isoformat(),
            }
            for task in self._auth_tasks.values()
        ]
        return {
            "is_running": self._is_running,
            "active_task_count": len(active_tasks),
            "active_tasks": active_tasks,
        }

    async def _finalize_auth(self, task_id: str) -> str:
        """
        核心：提取登录凭证并入库
        """
        task = self._auth_tasks.get(task_id)
        if not task:
            return json.dumps({"success": False, "message": "任务已失效"})

        logger.info(f"[Auth] 确认授权: {task_id}")

        try:
            # 提取 storage_state
            storage_state = await task.context.storage_state()
            cookies = storage_state.get("cookies", [])

            # 平台关键 Cookie 验证
            platform_checks = {
                "zhihu": "z_c0|z_cari0",
                "baijiahao": "BDUSS|BDUSS_BFESS|STOKEN|PTOKEN",
                "toutiao": "sessionid|sid_tt",
                "wenku": "BDUSS|STOKEN",
                "tieba": "BDUSS|STOKEN|BDUSS_BFESS",
                "penguin": "uin|skey|p_sktkt",
                "weixin": "slave_userinfo|data_bizuin|pass_ticket|pt2gguin",
                "wangyi": "NTES_SESS|S_INFO",
                "sohu": "ppinf|pprdig",
                "jianshu": "remember_user_token|_m7e_session",
                "juejin": "sessionid|sessionid_ss|passport_csrf_token|sid_tt",
                "zijie": "sessionid|sid_tt",
                "xiaohongshu": "xhs_web_session|webid|web_session|webId",
                "bilibili": "bili_jct|SESSDATA|DedeUserID|DedeUserID__ckMd5",
                "douyin": "sessionid|sessionid_ss|sid_guard|sid_tt|uid_tt",
                "kuaishou": "userId|token|kuaishou.server_st",
                "doubao": "sessionid|s_v_web_id|passport_csrf_token",
                "deepseek": "sessionid|ds_session|auth_token",
                "qianwen": "cna|login_aliyunid|isg",
            }

            key_cookie_str = platform_checks.get(task.platform)
            has_auth = True

            if key_cookie_str:
                required_keys = key_cookie_str.split("|")
                has_auth = any(c["name"].lower() in [k.lower() for k in required_keys] for c in cookies)

                # URL 负面排除：仍在登录页则拒绝
                current_url = task.page.url if task.page else ""
                url_lower = current_url.lower()
                login_patterns = ["/login", "/signin", "/sign_in", "/passport", "/account/"]
                if any(x in url_lower for x in login_patterns):
                    has_auth = False
                    logger.warning(f"[Auth] 仍在登录页: {current_url}")

                if not has_auth:
                    return json.dumps({"success": False, "message": "未检测到登录凭证，请确认已完成登录"})

            # 提取用户名
            try:
                username = await self._extract_username(task.page, task.platform)
            except Exception as e:
                logger.warning(f"[Auth] 提取用户名失败: {e}")
                username = None

            # 数据库操作
            db = self._get_db()
            if not db:
                return json.dumps({"success": False, "message": "数据库连接失败"})

            try:
                from backend.database.models import Account

                enc_cookies = encrypt_cookies(cookies)
                enc_storage = encrypt_storage_state(storage_state)

                if task.account_id:
                    # 更新现有账号
                    account = db.query(Account).filter(Account.id == task.account_id).first()
                    if account:
                        account.cookies = enc_cookies
                        account.storage_state = enc_storage
                        account.username = username or account.username
                        account.status = 1
                        account.last_auth_time = datetime.now()
                        db.commit()
                        logger.success(f"[Auth] 账号 {account.account_name} 更新成功")
                else:
                    # 创建新账号
                    name = task.account_name or f"{PLATFORMS[task.platform]['name']}_{username or 'User'}"
                    account = Account(
                        platform=task.platform,
                        account_name=name,
                        username=username,
                        cookies=enc_cookies,
                        storage_state=enc_storage,
                        status=1,
                        last_auth_time=datetime.now(),
                        user_id=task.user_id,
                    )
                    db.add(account)
                    db.commit()
                    db.refresh(account)
                    task.created_account_id = account.id
                    logger.success(f"[Auth] 新账号 {name} 创建成功")

                task.status = "success"

                # AI 平台同步到 session_manager
                if task.platform in ("doubao", "qianwen", "deepseek") and task.user_id:
                    try:
                        from backend.services.session_manager import secure_session_manager

                        await secure_session_manager.save_session(
                            user_id=task.user_id,
                            project_id=1,
                            platform=task.platform,
                            storage_state=storage_state,
                            is_new_login=True,
                        )
                    except Exception as sync_err:
                        logger.warning(f"[Auth] AI平台session同步失败: {sync_err}")

                # WebSocket 通知
                if self._ws_callback:
                    await self._ws_callback(
                        {
                            "type": "auth_complete",
                            "task_id": task_id,
                            "success": True,
                            "platform": task.platform,
                        }
                    )

                # 注意：不再立即延时关闭任务。
                # 旧逻辑会在 status='success' 后 5 秒强制 close_auth_task，前端轮询
                # GET /accounts/auth/status/{task_id} 经常撞上 404，导致 sessionProgress
                # 永远 add('account') 失败、引导卡死在"绑定发布账号"。
                # 现在改为：
                #   - 后端保留成功任务，由前端 confirm_auth 显式清理（也会触发前端推进引导）
                #   - 超 5 分钟未确认的 success 任务由 _cleanup_expired_tasks 兜底回收
                return json.dumps({"success": True, "message": "授权成功！账号已保存"})

            except Exception as e:
                db.rollback()
                logger.error(f"[Auth] 数据库错误: {e}")
                return json.dumps({"success": False, "message": str(e)})
            finally:
                db.close()

        except Exception as e:
            logger.error(f"[Auth] 处理异常: {e}")
            return json.dumps({"success": False, "message": str(e)})

    async def _delayed_close_task(self, task_id: str):
        """延时关闭任务"""
        await asyncio.sleep(5)
        await self.close_auth_task(task_id)

    async def close_auth_task(self, task_id: str):
        """关闭任务资源"""
        task = self._auth_tasks.get(task_id)
        if task:
            if task.context:
                try:
                    await task.context.close()
                except Exception as e:
                    logger.debug(f"[Auth] 关闭上下文失败: {e}")
            if task_id in self._auth_tasks:
                del self._auth_tasks[task_id]
            logger.info(f"[Auth] 任务已关闭: {task_id}")

    async def _cleanup_expired_tasks(self, timeout_minutes: int = 5):
        """清理超时任务

        覆盖三类状态：
        - pending / running：一直未结束的授权，5 分钟后判为超时
        - success：前端从未 confirm、也没主动 cancel 的兜底清理，关闭浏览器上下文
        """
        from datetime import timedelta

        now = datetime.now()
        expired = [
            tid
            for tid, task in self._auth_tasks.items()
            if task.status in ("pending", "running", "success")
            and now - task.created_at > timedelta(minutes=timeout_minutes)
        ]
        for tid in expired:
            task = self._auth_tasks.get(tid)
            if task:
                if task.status in ("pending", "running"):
                    task.status = "timeout"
                    task.error_message = f"授权超时（{timeout_minutes}分钟）"
                else:
                    # success 状态兜底清理，仅记录、状态保留 success 让接口返回仍准确
                    logger.info(f"[Auth] 清理未确认的成功任务: {tid}")
            await self.close_auth_task(tid)
        if expired:
            logger.info(f"[Auth] 清理了 {len(expired)} 个过期任务")

    async def _extract_username(self, page: Page, platform: str) -> Optional[str]:
        """从页面提取用户名"""
        try:
            # 通用选择器
            selectors_map = {
                "zhihu": [".AppHeader-profileText", ".UserLink-link"],
                "toutiao": [".user-name", ".name"],
                "baijiahao": [".user-name", ".name"],
                "bilibili": [".username-text", ".user-nick"],
                "douyin": [".user-name", ".username"],
                "doubao": ['[data-e2e="user-nickname"]', ".user-name"],
                "qianwen": [".username", ".user-name"],
                "deepseek": [".username", ".user-name"],
            }

            selectors = selectors_map.get(platform, [".user-name", ".name", ".username"])

            for s in selectors:
                try:
                    el = await page.query_selector(s)
                    if el:
                        text = await el.text_content()
                        if text and text.strip():
                            return text.strip()
                except Exception:
                    continue

            return None
        except Exception:
            return None

    # ==================== 发布相关 ====================

    async def execute_publish(
        self,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
        manual_event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """执行发布任务"""
        start_time = time.time()
        article_id = getattr(article, "id", None)
        account_id = getattr(account, "id", None)
        logger.info(
            f"🚀 [Publish] 开始发布: platform={account.platform} article_id={article_id} "
            f"account_id={account_id} title={getattr(article, 'title', '')[:40]} "
            f"declare_ai_content={declare_ai_content}"
        )
        await self.start()

        publisher = registry.get(account.platform)
        if not publisher:
            logger.error(f"[Publish] 平台适配器未注册: platform={account.platform} article_id={article_id}")
            return {"success": False, "error_msg": f"未找到平台 {account.platform} 的适配器"}

        context = None
        try:
            # 解密 Session
            state_data = {}
            if account.storage_state:
                try:
                    decrypted = decrypt_storage_state(account.storage_state)
                    state_data = decrypted if decrypted else json.loads(account.storage_state)

                    if isinstance(state_data, dict) and "cookies" not in state_data and account.cookies:
                        state_data["cookies"] = decrypt_cookies(account.cookies)
                except Exception as exc:
                    logger.warning(f"[Publish] 账号 {account.account_name}(id={account_id}) Session解析失败: {exc}")

            fallback_cookies = None
            if account.cookies:
                try:
                    fallback_cookies = decrypt_cookies(account.cookies)
                except Exception as exc:
                    logger.warning(f"[Publish] 账号 {account.account_name}(id={account_id}) Cookie解密失败: {exc}")

            if state_data or fallback_cookies:
                state_data = normalize_platform_storage_state(account.platform, state_data, fallback_cookies)
            logger.debug(
                f"[Publish] 会话加载完成: platform={account.platform} account_id={account_id} "
                f"state={bool(state_data)} cookies={bool(fallback_cookies)}"
            )

            context = await self._browser.new_context(
                storage_state=state_data if state_data else None,
                viewport={"width": 1280, "height": 800},
            )

            page = await context.new_page()
            logger.debug(f"[Publish] 浏览器上下文已创建: platform={account.platform} article_id={article_id}")
            if hasattr(publisher, "set_manual_event_callback"):
                publisher.set_manual_event_callback(manual_event_callback)
            try:
                result = await publisher.publish(page, article, account, declare_ai_content=declare_ai_content)
            finally:
                if hasattr(publisher, "set_manual_event_callback"):
                    publisher.set_manual_event_callback(None)

            elapsed = time.time() - start_time
            if result.get("success"):
                logger.success(
                    f"✅ [Publish] 发布成功: platform={account.platform} article_id={article_id} "
                    f"account_id={account_id} elapsed={elapsed:.1f}s"
                )
            else:
                logger.error(
                    f"❌ [Publish] 发布失败: platform={account.platform} article_id={article_id} "
                    f"account_id={account_id} error={result.get('error_msg', '未知错误')} elapsed={elapsed:.1f}s"
                )
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.exception(
                f"❌ [Publish] 执行异常: platform={account.platform} article_id={article_id} "
                f"account_id={account_id} error={e} elapsed={elapsed:.1f}s"
            )
            return {"success": False, "error_msg": str(e)}
        finally:
            if context:
                await context.close()


# 全局单例
playwright_mgr = PlaywrightManager()
