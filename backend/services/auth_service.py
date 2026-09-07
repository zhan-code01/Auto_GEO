# -*- coding: utf-8 -*-
"""
授权服务
处理AI平台的Web端授权流程
直接启动本地浏览器进行授权
"""

import asyncio
import uuid
import os
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger
from backend.utils.asyncio_compat import configure_windows_asyncio_policy

# ==================== Windows asyncio subprocess 兼容性修复 ====================
if sys.platform == "win32":
    try:
        configure_windows_asyncio_policy()
    except AttributeError:
        import warnings

        warnings.warn("Python版本过低，Windows ProactorEventLoopPolicy不可用")
# ==================== 修复结束 ====================

from playwright.async_api import async_playwright, Browser

from backend.config import (
    AI_PLATFORMS,
    BROWSER_ARGS,
    DEFAULT_USER_AGENT,
)
from backend.services.session_manager import secure_session_manager


class AuthService:
    """
    授权服务
    管理AI平台的授权流程
    直接启动本地浏览器，无需CDP/noVNC
    """

    def __init__(self):
        """
        初始化授权服务
        """
        self._active_auth_sessions: Dict[str, Dict[str, Any]] = {}
        self._auth_status: Dict[str, Dict[str, Any]] = {}
        self._playwright = None  # 用于启动浏览器

        logger.info("授权服务初始化: 直接启动本地浏览器模式")

    async def start_auth_flow(self, user_id: int, project_id: int, platforms: List[str]) -> Dict[str, Any]:
        """
        开始授权流程

        Args:
            user_id: 用户ID
            project_id: 项目ID
            platforms: 要授权的平台列表

        Returns:
            授权流程信息
        """
        try:
            # 验证参数
            if not all([user_id, project_id, platforms]):
                return {"success": False, "error": "参数不完整", "error_code": "INVALID_PARAMS"}

            # 验证平台
            valid_platforms = []
            for platform in platforms:
                if platform in AI_PLATFORMS:
                    valid_platforms.append(platform)
                else:
                    logger.warning(f"未知平台: {platform}")

            if not valid_platforms:
                return {"success": False, "error": "没有有效的平台", "error_code": "NO_VALID_PLATFORMS"}

            # 生成授权会话ID
            auth_session_id = str(uuid.uuid4())

            # 初始化授权状态
            self._auth_status[auth_session_id] = {
                "user_id": user_id,
                "project_id": project_id,
                "platforms": [
                    {"platform": platform, "status": "pending", "url": None, "error": None}
                    for platform in valid_platforms
                ],
                "current_platform_index": 0,
                "started_at": datetime.now().isoformat(),
                "status": "in_progress",
            }

            logger.info(
                f"授权流程开始: auth_session_id={auth_session_id}, user_id={user_id}, project_id={project_id}, platforms={valid_platforms}"
            )

            return {
                "success": True,
                "auth_session_id": auth_session_id,
                "platforms": valid_platforms,
                "message": "授权流程已启动",
            }

        except Exception as e:
            logger.error(f"开始授权流程失败: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    async def get_auth_status(self, auth_session_id: str) -> Dict[str, Any]:
        """
        获取授权状态

        Args:
            auth_session_id: 授权会话ID

        Returns:
            授权状态
        """
        try:
            status = self._auth_status.get(auth_session_id)

            if not status:
                return {"success": False, "error": "授权会话不存在", "error_code": "SESSION_NOT_FOUND"}

            return {"success": True, "status": status}

        except Exception as e:
            logger.error(f"获取授权状态失败: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    async def start_platform_auth(self, auth_session_id: str, platform: str) -> Dict[str, Any]:
        """
        开始单个平台的授权

        Args:
            auth_session_id: 授权会话ID
            platform: 平台标识

        Returns:
            授权URL和状态
        """
        try:
            # 验证授权会话
            status = self._auth_status.get(auth_session_id)
            if not status:
                return {"success": False, "error": "授权会话不存在", "error_code": "SESSION_NOT_FOUND"}

            # 验证平台
            if platform not in AI_PLATFORMS:
                return {"success": False, "error": "未知平台", "error_code": "UNKNOWN_PLATFORM"}

            # 检查平台是否在授权列表中
            platform_info = next((p for p in status["platforms"] if p["platform"] == platform), None)

            if not platform_info:
                return {"success": False, "error": "平台不在授权列表中", "error_code": "PLATFORM_NOT_IN_LIST"}

            # 启动浏览器进行授权
            browser, context, page = await self._launch_browser_for_auth()

            if not all([browser, context, page]):
                return {"success": False, "error": "浏览器启动失败", "error_code": "BROWSER_LAUNCH_FAILED"}

            # 导航到平台页面
            platform_config = AI_PLATFORMS[platform]
            platform_url = platform_config.get("url", "")

            if platform_url:
                try:
                    logger.info(f"导航到平台页面: {platform_url}")
                    await page.goto(platform_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    logger.error(f"导航失败: {e}")

            # 监听新窗口并置顶
            async def _bring_page_to_front(p):
                try:
                    await p.bring_to_front()
                except Exception:
                    pass

            def _on_context_page(p):
                if p is page:
                    return
                asyncio.create_task(_bring_page_to_front(p))

            context.on("page", _on_context_page)

            # 保存活跃的授权会话
            self._active_auth_sessions[auth_session_id] = {
                "browser": browser,
                "context": context,
                "page": page,
                "platform": platform,
                "user_id": status["user_id"],
                "project_id": status["project_id"],
            }

            # 更新状态
            platform_info["status"] = "in_progress"
            platform_info["url"] = None

            logger.info(f"平台授权开始: auth_session_id={auth_session_id}, platform={platform}")

            # 启动后台任务检测登录状态
            asyncio.create_task(self._monitor_login_status(auth_session_id, platform))

            return {
                "success": True,
                "platform": platform,
                "auth_url": None,
                "message": "授权窗口已打开，请完成登录操作",
            }

        except Exception as e:
            logger.error(f"开始平台授权失败: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    async def _monitor_login_status(self, auth_session_id: str, platform: str):
        """
        监控登录状态，当用户完成登录后自动保存会话

        Args:
            auth_session_id: 授权会话ID
            platform: 平台标识
        """
        try:
            logger.info(f"开始监控登录状态: auth_session_id={auth_session_id}, platform={platform}")

            # 检查活跃会话是否存在
            if auth_session_id not in self._active_auth_sessions:
                logger.warning(f"活跃会话不存在: {auth_session_id}")
                return

            session = self._active_auth_sessions[auth_session_id]
            page = session["page"]
            context = session["context"]
            browser = session["browser"]
            user_id = session["user_id"]
            project_id = session["project_id"]

            # 给页面一些加载时间
            logger.info(f"等待页面加载: platform={platform}")
            await asyncio.sleep(3)

            # 监控登录状态，最多等待10分钟
            max_wait_time = 600  # 10分钟
            check_interval = 3  # 3秒检查一次
            elapsed_time = 0

            # 记录页面加载状态
            page_loaded = False

            while elapsed_time < max_wait_time:
                try:
                    # 检查页面是否加载完成
                    if not page_loaded:
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=30000)
                            page_loaded = True
                            logger.info(f"页面加载完成: platform={platform}")
                        except Exception as e:
                            logger.warning(f"页面加载超时: {e}, platform={platform}")

                    # 检查是否存在登录元素
                    login_indicators = [
                        "[class*='login']",
                        "[id*='login']",
                        "[class*='auth']",
                        "[id*='auth']",
                        "button:has-text('登录')",
                        "button:has-text('Sign in')",
                        "button:has-text('立即登录')",
                        "div:has-text('登录'):visible",
                    ]

                    # 针对特定平台的精确登录选择器
                    if platform == "doubao":
                        login_indicators.extend(
                            [
                                "[data-testid*='login']",
                                "header button:has-text('登录')",
                                "div[class*='right'] :text('登录')",
                            ]
                        )
                    elif platform == "qianwen":
                        login_indicators.extend(["div[class*='login']", "div[class*='sign-in']", "[class*='auth-btn']"])

                    has_login_elements = False
                    try:
                        for selector in login_indicators:
                            try:
                                if "text=" in selector or "has-text" in selector:
                                    elements = await page.query_selector_all(selector)
                                    for el in elements:
                                        if await el.is_visible():
                                            text = await el.inner_text()
                                            if text and len(text.strip()) < 10 and ("登录" in text or "Sign" in text):
                                                has_login_elements = True
                                                logger.info(
                                                    f"检测到登录入口: {selector} ('{text}'), platform={platform}"
                                                )
                                                break
                                else:
                                    element = await page.query_selector(selector)
                                    if element and await element.is_visible():
                                        has_login_elements = True
                                        logger.info(f"检测到登录入口: {selector}, platform={platform}")
                                        break
                            except Exception:
                                continue
                            if has_login_elements:
                                break
                    except Exception as e:
                        logger.error(f"检查登录元素失败: {e}")

                    # 检查是否有错误信息
                    error_indicators = [
                        "[class*='error']",
                        "[id*='error']",
                        "[class*='warning']",
                        "[id*='warning']",
                        "[class*='alert']",
                    ]

                    has_error = False
                    try:
                        for selector in error_indicators:
                            try:
                                elements = await page.query_selector_all(selector)
                                if elements:
                                    has_error = True
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        logger.error(f"检查错误信息失败: {e}")

                    # 优先检查明确的成功标志
                    success_indicators = [
                        "textarea",
                        "[contenteditable='true']",
                        "div[class*='chat-input']",
                        "[data-testid*='input']",
                        # 通义千问
                        "textarea[placeholder*='提问']",
                        "textarea[placeholder*='千问']",
                        "[class*='ant-input']",
                        # 豆包
                        "textarea[placeholder*='输入']",
                        "textarea[placeholder*='发消息']",
                        # DeepSeek
                        "textarea[placeholder*='Message']",
                        "textarea[placeholder*='消息']",
                    ]

                    has_success_element = False
                    try:
                        for selector in success_indicators:
                            try:
                                element = await page.query_selector(selector)
                                if element and await element.is_visible():
                                    has_success_element = True
                                    logger.info(f"检测到明确的登录成功标志: {selector}, platform={platform}")
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        logger.error(f"检查成功标志失败: {e}")

                    login_successful = False

                    # 判定逻辑：
                    # 1. 只要检测到登录入口，无论有没有输入框，都视为未登录
                    # 2. 没有登录入口 且 (有成功标志 或 页面干净) -> 成功

                    if has_login_elements:
                        login_successful = False
                        logger.debug(f"{platform}平台等待登录: 检测到登录入口")
                    elif has_success_element:
                        logger.info(f"初步检测到登录成功(有输入框): platform={platform}，进行二次确认...")
                        await asyncio.sleep(3)

                        # 二次检查登录入口
                        double_check_login = False
                        try:
                            for selector in login_indicators:
                                try:
                                    if "text=" in selector or "has-text" in selector:
                                        elements = await page.query_selector_all(selector)
                                        for el in elements:
                                            if await el.is_visible():
                                                text = await el.inner_text()
                                                if (
                                                    text
                                                    and len(text.strip()) < 10
                                                    and ("登录" in text or "Sign" in text)
                                                ):
                                                    double_check_login = True
                                                    break
                                    else:
                                        element = await page.query_selector(selector)
                                        if element and await element.is_visible():
                                            double_check_login = True
                                            break
                                except Exception:
                                    continue
                                if double_check_login:
                                    break
                        except Exception:
                            pass

                        if double_check_login:
                            logger.info(f"二次确认发现登录入口，撤销成功判定: platform={platform}")
                            login_successful = False
                        else:
                            logger.info(f"二次确认通过，登录成功: platform={platform}")
                            login_successful = True

                    elif page_loaded and not has_error:
                        if platform == "deepseek":
                            login_successful = False
                        else:
                            logger.info(f"根据页面状态判定登录成功(无登录按钮且无错误): platform={platform}")
                            login_successful = True
                    else:
                        logger.debug(
                            f"{platform}平台继续等待: 页面加载={page_loaded}, 登录元素={has_login_elements}, 成功元素={has_success_element}"
                        )
                        await asyncio.sleep(check_interval)
                        elapsed_time += check_interval
                        continue

                    # 检测到登录成功，获取存储状态并保存
                    if login_successful:
                        logger.info(f"检测到登录成功: platform={platform}")
                        storage_state = await context.storage_state()

                        # 保存会话 (标记为新登录)
                        save_result = await secure_session_manager.save_session(
                            user_id, project_id, platform, storage_state, is_new_login=True
                        )

                        if save_result:
                            logger.info(f"会话保存成功: platform={platform}")
                        else:
                            logger.error(f"会话保存失败: platform={platform}")

                        # 关闭浏览器
                        await self._close_browser(browser)

                        # 清理活跃会话
                        del self._active_auth_sessions[auth_session_id]

                        # 更新状态
                        status = self._auth_status.get(auth_session_id)
                        if status:
                            platform_info = next((p for p in status["platforms"] if p["platform"] == platform), None)
                            if platform_info:
                                if save_result:
                                    platform_info["status"] = "completed"
                                    platform_info["error"] = None
                                else:
                                    platform_info["status"] = "failed"
                                    platform_info["error"] = "会话保存失败"

                        logger.info(f"登录监控完成: platform={platform}, save_result={save_result}")
                        return

                except Exception as e:
                    logger.error(f"监控登录状态失败: {e}")

                # 等待一段时间后再次检查
                await asyncio.sleep(check_interval)
                elapsed_time += check_interval

            # 超时，关闭浏览器
            logger.warning(f"登录监控超时: platform={platform}")
            await self._close_browser(browser)

            # 清理活跃会话
            if auth_session_id in self._active_auth_sessions:
                del self._active_auth_sessions[auth_session_id]

            # 更新状态
            status = self._auth_status.get(auth_session_id)
            if status:
                platform_info = next((p for p in status["platforms"] if p["platform"] == platform), None)
                if platform_info:
                    platform_info["status"] = "failed"
                    platform_info["error"] = "登录超时"

        except Exception as e:
            logger.error(f"监控登录状态异常: {e}")

            # 清理资源
            if auth_session_id in self._active_auth_sessions:
                try:
                    browser = self._active_auth_sessions[auth_session_id].get("browser")
                    if browser:
                        await self._close_browser(browser)
                except Exception:
                    pass
                del self._active_auth_sessions[auth_session_id]

    async def complete_platform_auth(self, auth_session_id: str, platform: str) -> Dict[str, Any]:
        """
        完成平台授权

        Args:
            auth_session_id: 授权会话ID
            platform: 平台标识

        Returns:
            授权结果
        """
        try:
            # 检查授权会话状态
            status = self._auth_status.get(auth_session_id)
            if not status:
                return {"success": False, "error": "授权会话不存在", "error_code": "SESSION_NOT_FOUND"}

            # 检查平台是否在授权列表中
            platform_info = next((p for p in status["platforms"] if p["platform"] == platform), None)
            if not platform_info:
                return {"success": False, "error": "平台不在授权列表中", "error_code": "PLATFORM_NOT_IN_LIST"}

            # 检查活跃会话
            auth_session = self._active_auth_sessions.get(auth_session_id)
            if auth_session:
                return {
                    "success": False,
                    "error": "授权流程仍在进行中，请完成登录后再检查",
                    "error_code": "AUTH_IN_PROGRESS",
                }

            # 验证平台会话状态
            user_id = status["user_id"]
            project_id = status["project_id"]
            session_status = await secure_session_manager.get_session_status(user_id, project_id, platform)

            if session_status["status"] == "valid":
                logger.info(f"平台授权验证成功: auth_session_id={auth_session_id}, platform={platform}")
                platform_info["status"] = "completed"
                platform_info["error"] = None
                return {"success": True, "platform": platform, "message": "授权成功"}
            else:
                logger.warning(
                    f"平台授权验证失败: auth_session_id={auth_session_id}, platform={platform}, status={session_status['status']}"
                )
                platform_info["status"] = "failed"
                platform_info["error"] = f"授权验证失败: {session_status.get('reason', '未知错误')}"
                return {"success": False, "error": "授权验证失败，请重新尝试", "error_code": "AUTH_VALIDATION_FAILED"}

        except Exception as e:
            logger.error(f"完成平台授权失败: {e}")

            # 清理资源
            if auth_session_id in self._active_auth_sessions:
                try:
                    browser = self._active_auth_sessions[auth_session_id].get("browser")
                    if browser:
                        await self._close_browser(browser)
                except Exception:
                    pass
                del self._active_auth_sessions[auth_session_id]

            # 更新状态
            status = self._auth_status.get(auth_session_id)
            if status:
                platform_info = next((p for p in status["platforms"] if p["platform"] == platform), None)
                if platform_info:
                    platform_info["status"] = "failed"
                    platform_info["error"] = f"授权失败: {str(e)}"

            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    async def cancel_auth_flow(self, auth_session_id: str) -> Dict[str, Any]:
        """
        取消授权流程

        Args:
            auth_session_id: 授权会话ID

        Returns:
            取消结果
        """
        try:
            # 清理活跃会话
            if auth_session_id in self._active_auth_sessions:
                auth_session = self._active_auth_sessions[auth_session_id]
                browser = auth_session.get("browser")
                if browser:
                    await self._close_browser(browser)
                del self._active_auth_sessions[auth_session_id]

            # 更新状态
            if auth_session_id in self._auth_status:
                self._auth_status[auth_session_id]["status"] = "cancelled"

            logger.info(f"授权流程取消: auth_session_id={auth_session_id}")

            return {"success": True, "message": "授权流程已取消"}

        except Exception as e:
            logger.error(f"取消授权流程失败: {e}")
            return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

    async def _launch_browser_for_auth(self) -> tuple:
        """
        启动用于授权的浏览器
        直接启动本地浏览器（headless=False，用户可见）

        Returns:
            (browser, context, page) 元组
        """
        try:
            logger.info("🚀 正在启动本地浏览器...")

            # Windows下必须用ProactorEventLoop支持subprocess
            if sys.platform == "win32":
                try:
                    configure_windows_asyncio_policy()
                except Exception as e:
                    logger.error(f"设置事件循环策略失败: {e}")

            # 启动Playwright
            if self._playwright is None:
                self._playwright = await async_playwright().start()

            # 1. 尝试查找本地 Chrome 路径
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ]

            # Mac OS 支持
            if sys.platform == "darwin":
                chrome_paths = [
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                ]

            executable_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    executable_path = path
                    logger.info(f"✅ 找到本地 Chrome 浏览器: {path}")
                    break

            # 构建启动参数
            args = list(BROWSER_ARGS)

            # 关键：headless=False 让用户能看到浏览器窗口
            launch_options = {
                "headless": False,
                "args": args,
                "timeout": 30000,
            }

            if executable_path:
                launch_options["executable_path"] = executable_path

            # 启动浏览器
            logger.info(f"启动Chromium浏览器... headless=False, args={args}")

            browser = None
            try:
                browser = await self._playwright.chromium.launch(**launch_options)
            except Exception as browser_error:
                error_msg = str(browser_error)
                logger.warning(f"首次启动失败: {error_msg}")

                # 如果指定了本地Chrome但启动失败，尝试不使用executable_path
                if executable_path:
                    logger.info("尝试使用Playwright内置浏览器...")
                    launch_options.pop("executable_path", None)
                    try:
                        browser = await self._playwright.chromium.launch(**launch_options)
                    except Exception as inner_error:
                        logger.error(f"内置浏览器启动失败: {inner_error}")

                # 如果还是失败，尝试自动安装
                if not browser and "Executable doesn't exist" in error_msg:
                    logger.warning("检测到浏览器缺失，尝试自动安装...")
                    try:
                        process = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            "playwright",
                            "install",
                            "chromium",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await process.communicate()

                        if process.returncode == 0:
                            logger.info("浏览器安装成功，重试启动...")
                            browser = await self._playwright.chromium.launch(**launch_options)
                        else:
                            logger.error(f"自动安装失败: {stderr.decode()}")
                            raise Exception("自动安装浏览器失败，请手动执行 'playwright install'")
                    except Exception as install_error:
                        logger.error(f"自动安装过程异常: {install_error}")
                        raise install_error

                if not browser:
                    await self._playwright.stop()
                    self._playwright = None
                    raise Exception(f"浏览器启动失败: {error_msg}")

            # 创建上下文和页面
            logger.info("创建浏览器上下文...")
            context = await browser.new_context(no_viewport=True, user_agent=DEFAULT_USER_AGENT)
            page = await context.new_page()

            logger.info("✅ 本地浏览器启动成功")
            return browser, context, page

        except Exception as e:
            logger.error(f"❌ 浏览器启动失败: {e}")
            return None, None, None

    async def _close_browser(self, browser: Browser):
        """
        关闭浏览器

        Args:
            browser: Playwright Browser对象
        """
        try:
            if browser:
                await browser.close()
                logger.info("浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器失败: {e}")

    async def cleanup_expired_sessions(self):
        """
        清理过期的授权会话
        """
        try:
            expired_session_ids = []
            now = datetime.now()

            # 清理活跃会话（超过30分钟）
            for session_id, session_data in list(self._active_auth_sessions.items()):
                try:
                    browser = session_data.get("browser")
                    if browser:
                        await self._close_browser(browser)
                except Exception:
                    pass
                expired_session_ids.append(session_id)

            # 清理状态会话（超过2小时）
            for session_id, status_data in list(self._auth_status.items()):
                started_at = datetime.fromisoformat(status_data.get("started_at", ""))
                if now - started_at > timedelta(hours=2):
                    expired_session_ids.append(session_id)

            # 执行清理
            for session_id in set(expired_session_ids):
                if session_id in self._active_auth_sessions:
                    del self._active_auth_sessions[session_id]
                if session_id in self._auth_status:
                    del self._auth_status[session_id]

            if expired_session_ids:
                logger.info(f"清理过期会话: {len(set(expired_session_ids))} 个")

        except Exception as e:
            logger.error(f"清理过期会话失败: {e}")


# 全局单例
auth_service = AuthService()
