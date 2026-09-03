# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

# 项目 backend 根目录（spec 文件所在目录）
BACKEND_ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['scripts\\local_client_publish_runner.py'],
    pathex=[BACKEND_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'loguru',
        'playwright',
        'playwright.async_api',
        'playwright._impl',
        'playwright._impl._async_base',
        'playwright._impl._browser',
        'playwright._impl._browser_context',
        'playwright._impl._connection',
        'playwright._impl._element_handle',
        'playwright._impl._frame',
        'playwright._impl._input',
        'playwright._impl._network',
        'playwright._impl._page',
        'playwright._impl._api_structures',
        'playwright._impl._errors',
        'playwright._impl._helper',
        'playwright._impl._impl_to_api_mapping',
        'playwright._impl._js_handle',
        'playwright._impl._path_utils',
        'playwright._impl._sync_base',
        'playwright._impl._transport',
        'playwright._impl._wait_helper',
        'pyee',
        'pyee.asyncio',
        'pyee.base',
        'pyee.twisted',
        'pyee.trio',
        'greenlet',
        'backend.config',
        'backend.services.playwright.publishers',
        'backend.services.playwright.base_publisher',
    ] + collect_submodules('playwright._impl'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='local_client_publish_runner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
