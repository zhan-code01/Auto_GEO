# -*- coding: utf-8 -*-
"""
AutoGeo Backend Entry Point
允许使用: python -m backend
"""

from backend.main import app

if __name__ == "__main__":
    import uvicorn
    from backend.config import HOST, PORT

    # log_config=None：uvicorn 日志统一走 loguru 桥接；access_log=False：访问日志由 AccessLogMiddleware 统一记录
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", access_log=False, log_config=None)
