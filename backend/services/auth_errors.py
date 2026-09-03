# -*- coding: utf-8 -*-
"""
授权错误码定义
统一管理授权过程中的错误码和错误信息
"""


class AuthErrorCodes:
    """
    授权错误码类
    定义所有授权相关的错误码
    """

    # 通用错误
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 内部错误
    INVALID_PARAMS = "INVALID_PARAMS"  # 参数无效
    NETWORK_ERROR = "NETWORK_ERROR"  # 网络错误
    TIMEOUT = "TIMEOUT"  # 超时

    # 授权流程错误
    AUTH_FLOW_NOT_FOUND = "AUTH_FLOW_NOT_FOUND"  # 授权流程不存在
    AUTH_FLOW_CANCELLED = "AUTH_FLOW_CANCELLED"  # 授权流程已取消
    AUTH_FLOW_COMPLETED = "AUTH_FLOW_COMPLETED"  # 授权流程已完成

    # 平台错误
    UNKNOWN_PLATFORM = "UNKNOWN_PLATFORM"  # 未知平台
    PLATFORM_NOT_IN_LIST = "PLATFORM_NOT_IN_LIST"  # 平台不在授权列表中
    PLATFORM_AUTH_FAILED = "PLATFORM_AUTH_FAILED"  # 平台授权失败

    # 浏览器错误
    BROWSER_LAUNCH_FAILED = "BROWSER_LAUNCH_FAILED"  # 浏览器启动失败
    BROWSER_CONNECTION_LOST = "BROWSER_CONNECTION_LOST"  # 浏览器连接丢失

    # 页面元素错误
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"  # 元素未找到
    ELEMENT_NOT_INTERACTABLE = "ELEMENT_NOT_INTERACTABLE"  # 元素不可交互

    # 登录/验证错误
    LOGIN_REQUIRED = "LOGIN_REQUIRED"  # 需要登录
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"  # 需要验证码
    LOGIN_FAILED = "LOGIN_FAILED"  # 登录失败
    VERIFICATION_FAILED = "VERIFICATION_FAILED"  # 验证失败

    # 会话错误
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"  # 会话不存在
    SESSION_INVALID = "SESSION_INVALID"  # 会话无效
    SESSION_EXPIRED = "SESSION_EXPIRED"  # 会话过期
    SESSION_SAVE_FAILED = "SESSION_SAVE_FAILED"  # 会话保存失败

    # 存储状态错误
    STORAGE_STATE_ERROR = "STORAGE_STATE_ERROR"  # 存储状态错误
    STORAGE_STATE_INVALID = "STORAGE_STATE_INVALID"  # 存储状态无效

    # 用户操作错误
    USER_CANCELLED = "USER_CANCELLED"  # 用户取消
    USER_TIMEOUT = "USER_TIMEOUT"  # 用户操作超时


class AuthErrorMessages:
    """
    授权错误信息类
    为每个错误码提供对应的错误信息
    """

    ERROR_MESSAGES = {
        # 通用错误
        AuthErrorCodes.INTERNAL_ERROR: "服务器内部错误",
        AuthErrorCodes.INVALID_PARAMS: "参数无效或不完整",
        AuthErrorCodes.NETWORK_ERROR: "网络连接失败",
        AuthErrorCodes.TIMEOUT: "操作超时",
        # 授权流程错误
        AuthErrorCodes.AUTH_FLOW_NOT_FOUND: "授权流程不存在",
        AuthErrorCodes.AUTH_FLOW_CANCELLED: "授权流程已取消",
        AuthErrorCodes.AUTH_FLOW_COMPLETED: "授权流程已完成",
        # 平台错误
        AuthErrorCodes.UNKNOWN_PLATFORM: "未知的AI平台",
        AuthErrorCodes.PLATFORM_NOT_IN_LIST: "平台不在授权列表中",
        AuthErrorCodes.PLATFORM_AUTH_FAILED: "平台授权失败",
        # 浏览器错误
        AuthErrorCodes.BROWSER_LAUNCH_FAILED: "浏览器启动失败",
        AuthErrorCodes.BROWSER_CONNECTION_LOST: "浏览器连接丢失",
        # 页面元素错误
        AuthErrorCodes.ELEMENT_NOT_FOUND: "页面元素未找到",
        AuthErrorCodes.ELEMENT_NOT_INTERACTABLE: "页面元素不可交互",
        # 登录/验证错误
        AuthErrorCodes.LOGIN_REQUIRED: "需要登录",
        AuthErrorCodes.CAPTCHA_REQUIRED: "需要验证码",
        AuthErrorCodes.LOGIN_FAILED: "登录失败",
        AuthErrorCodes.VERIFICATION_FAILED: "验证失败",
        # 会话错误
        AuthErrorCodes.SESSION_NOT_FOUND: "会话不存在",
        AuthErrorCodes.SESSION_INVALID: "会话无效",
        AuthErrorCodes.SESSION_EXPIRED: "会话已过期",
        AuthErrorCodes.SESSION_SAVE_FAILED: "会话保存失败",
        # 存储状态错误
        AuthErrorCodes.STORAGE_STATE_ERROR: "获取存储状态失败",
        AuthErrorCodes.STORAGE_STATE_INVALID: "存储状态无效",
        # 用户操作错误
        AuthErrorCodes.USER_CANCELLED: "用户取消操作",
        AuthErrorCodes.USER_TIMEOUT: "用户操作超时",
    }

    @classmethod
    def get_message(cls, error_code: str, default: str = "未知错误") -> str:
        """
        获取错误信息

        Args:
            error_code: 错误码
            default: 默认错误信息

        Returns:
            错误信息
        """
        return cls.ERROR_MESSAGES.get(error_code, default)


class AuthError(Exception):
    """
    授权错误异常类
    """

    def __init__(self, error_code: str, message: str = None, **kwargs):
        """
        初始化授权错误

        Args:
            error_code: 错误码
            message: 错误信息（可选，默认使用错误码对应的默认信息）
            **kwargs: 额外的错误上下文信息
        """
        if message is None:
            message = AuthErrorMessages.get_message(error_code)

        self.error_code = error_code
        self.message = message
        self.context = kwargs

        super().__init__(f"[{error_code}] {message}")


# 错误码分类
TEMPORARY_ERRORS = {
    # 临时错误，可重试
    AuthErrorCodes.NETWORK_ERROR,
    AuthErrorCodes.TIMEOUT,
    AuthErrorCodes.BROWSER_CONNECTION_LOST,
    AuthErrorCodes.ELEMENT_NOT_FOUND,  # 可能是页面加载问题
}

PERMANENT_ERRORS = {
    # 永久错误，不可重试
    AuthErrorCodes.INVALID_PARAMS,
    AuthErrorCodes.UNKNOWN_PLATFORM,
    AuthErrorCodes.PLATFORM_NOT_IN_LIST,
    AuthErrorCodes.CAPTCHA_REQUIRED,  # 需要人工处理
    AuthErrorCodes.LOGIN_FAILED,  # 登录凭据错误
    AuthErrorCodes.USER_CANCELLED,
}


def is_retryable_error(error_code: str) -> bool:
    """
    判断错误是否可重试

    Args:
        error_code: 错误码

    Returns:
        是否可重试
    """
    return error_code in TEMPORARY_ERRORS


def get_error_severity(error_code: str) -> str:
    """
    获取错误严重程度

    Args:
        error_code: 错误码

    Returns:
        严重程度: "critical", "error", "warning", "info"
    """
    severity_map = {
        # 严重错误
        AuthErrorCodes.INTERNAL_ERROR: "critical",
        AuthErrorCodes.BROWSER_LAUNCH_FAILED: "critical",
        AuthErrorCodes.LOGIN_FAILED: "critical",
        # 错误
        AuthErrorCodes.NETWORK_ERROR: "error",
        AuthErrorCodes.TIMEOUT: "error",
        AuthErrorCodes.PLATFORM_AUTH_FAILED: "error",
        AuthErrorCodes.SESSION_SAVE_FAILED: "error",
        # 警告
        AuthErrorCodes.CAPTCHA_REQUIRED: "warning",
        AuthErrorCodes.ELEMENT_NOT_FOUND: "warning",
        AuthErrorCodes.USER_TIMEOUT: "warning",
        # 信息
        AuthErrorCodes.USER_CANCELLED: "info",
        AuthErrorCodes.AUTH_FLOW_CANCELLED: "info",
    }

    return severity_map.get(error_code, "error")
