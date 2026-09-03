# -*- coding: utf-8 -*-
"""Standalone entry point for PyInstaller-packaged geo evaluation worker.

Electron spawns this exe directly instead of `python -m backend.workers.geo_evaluation_worker`,
so users don't need Python installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# PyInstaller 环境下 __file__ 指向临时目录，用 sys.executable 定位
if getattr(sys, 'frozen', False):
    # exe 在 resources/backend/scripts/dist/ 中
    # sys.executable -> resources/backend/scripts/dist/geo_evaluation_worker_runner.exe
    # 向上 3 级到 resources/backend/（backend 包根目录）
    ROOT = Path(sys.executable).resolve().parent.parent.parent
else:
    ROOT = Path(__file__).resolve().parent.parent

# 确保 backend 包可导入
sys.path.insert(0, str(ROOT))

from backend.workers.geo_evaluation_worker import main  # noqa: E402

if __name__ == "__main__":
    main()
