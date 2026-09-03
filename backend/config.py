# -*- coding: utf-8 -*-
"""
auto_geo 鍚庣閰嶇疆
铏界劧鏆磋簛锛屼絾閰嶇疆蹇呴』娓呮櫚锛?"""

import os
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from dotenv import load_dotenv

# ==================== 椤圭洰璺緞 ====================
# PyInstaller 打包环境下，__file__ 指向临时解压目录，需要用 sys.executable 定位真实路径
if getattr(sys, 'frozen', False):
    # exe 在 resources/backend/scripts/dist/ 中，向上三级到 resources/backend/（即项目根）
    BASE_DIR = Path(sys.executable).resolve().parent.parent.parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# 鍔犺浇鐜鍙橀
# PyInstaller 环境下 .env 不在打包资源中，load_dotenv 静默失败即可
if not getattr(sys, 'frozen', False):
    load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / ".cookies"

# 鏁版嵁搴撶褰曢渶瑕佸拰浠ｇ爜鐩綍鍒嗙锛屽惁鍒?Docker 鎸傝浇浼氳鐩栦唬鐮紒
# 鏈湴寮€鍙? backend/database/
# Docker 鐜: /app/database/ (鐙珛鐩綍锛屼笉瑕嗙洊浠ｇ爜)
_DOCKER_DB_DIR = Path("/app/database")
if _DOCKER_DB_DIR.exists() or os.getenv("ENVIRONMENT") == "production":
    # Docker 鐜锛氫娇鐢ㄧ嫭绔嬬殑鏁版鐩綍
    DATABASE_DIR = _DOCKER_DB_DIR
elif getattr(sys, 'frozen', False):
    # PyInstaller 打包环境：使用 exe 所在目录下的 database
    DATABASE_DIR = BASE_DIR / "database"
else:
    # 鏈湴寮€鍙戠澧冿細浣跨敤 backend/database
    DATABASE_DIR = BASE_DIR / "backend" / "database"

# 繚鐩綍瀛樺
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

# ==================== 搴旂敤閰嶇疆 ====================
APP_NAME = "AutoGeo Backend"
APP_VERSION = "2.0.0"
DEBUG = True

# ==================== 鏈嶅姟閰嶇疆 ====================
# 鐢熶骇鐜鐢?.0.0.0鐩戝惉鎵€鏈塈P锛孌ocker澶栭儴鎵嶈兘璁块棶
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8001"))  # 淇敼鐨勶細閬垮紑8000绔彛鐨刉indows娈嬬暀鍗犵敤闂
RELOAD = os.getenv("RELOAD", "false").lower() in {"1", "true", "yes", "on"}

# CORS閰嶇疆
# 娣诲姞鐢熶骇鏈嶅姟鍣↖P锛屽惁鍒欏墠绔細璺ㄥ煙鎶ラ敊
_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS = [
    "http://localhost:5179",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "capacitor://localhost",
    "http://localhost",
    # 铏氭嫙鏈?/ 灞€鍩熺綉璁块棶
    # 鐢熶骇鏈嶅姟鍣紙涓伙級
    # 鐢熶骇鏈嶅姟鍣紙澶囷級
]
# 浠庣幆澧冨彉閲忚拷鍔犻澶栫殑CORS婧
if _CORS_ORIGINS:
    CORS_ORIGINS.extend([origin.strip() for origin in _CORS_ORIGINS.split(",")])
CORS_ALLOW_ORIGIN_REGEX = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "") or None

# ==================== 鏁版嵁搴撻厤缃?====================
# PostgreSQL 鏄粯璁よ繍琛屾椂鏁版嵁搴撱€侱ATABASE_URL 蹇呴』鏄惧紡閰嶇疆銆?# 鏍煎紡绀轰緥锛?#   postgresql://autogeo:password@localhost:5432/autogeo
#   postgresql://autogeo:password@postgres:5432/autogeo  (Docker)
_RUNNING_UNDER_PYTEST = "pytest" in Path(os.getenv("_", "")).name.lower() or any(
    "pytest" in part.lower() for part in os.sys.argv
)

if _RUNNING_UNDER_PYTEST and os.getenv("TEST_DATABASE_URL"):
    DATABASE_URL = os.getenv("TEST_DATABASE_URL")
else:
    DATABASE_URL = os.getenv("DATABASE_URL")

if _RUNNING_UNDER_PYTEST and DATABASE_URL:
    db_name = (urlparse(DATABASE_URL).path or "").lstrip("/")
    allow_non_test_db = os.getenv("AUTOGEO_ALLOW_DEV_DB_TEST_CLEAN", "").lower() in {"1", "true", "yes", "on"}
    if not allow_non_test_db and "test" not in db_name.lower():
        raise ValueError(
            "Refusing to run pytest against non-test database "
            f"'{db_name}'. Set TEST_DATABASE_URL to a dedicated test database "
            "(for example postgresql://.../autogeo_test)."
        )
# DATABASE_URL 校验：worker 进程（exe 打包或 Python 模式）不需要数据库连接，
# 只通过 HTTP API 与后端通信，跳过校验
_is_worker_process = (
    getattr(sys, 'frozen', False)
    or os.getenv('AUTOGEO_WORKER_TOKEN') is not None
    or any('geo_evaluation_worker' in a for a in sys.argv)
)
if not DATABASE_URL and not _is_worker_process:
    raise ValueError(
        "DATABASE_URL is required. PostgreSQL is the only supported runtime database.\n"
        "Set DATABASE_URL=postgresql://user:password@host:5432/db in your .env file."
    )

if DATABASE_URL and not DATABASE_URL.lower().startswith(("postgresql://", "postgresql+")):
    raise ValueError(
        "Only PostgreSQL DATABASE_URL values are supported. "
        "Use postgresql://user:password@host:5432/db."
    )

# Database connection pool configuration.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))

# Runtime database type is fixed to PostgreSQL.
def get_database_type():
    """Return the configured runtime database type."""
    return "postgresql"

# ==================== 鍔犲瘑閰嶇疆 ====================
# AES-256鍔犲瘑瀵嗛挜锛?2瀛楄妭锛? 鐢熶骇鐜蹇呴』浠庣幆澧冨彉閲忚鍙
_encryption_key = os.getenv("AUTO_GEO_ENCRYPTION_KEY")
# worker 进程（exe 打包或 Python 模式回退）不需要加解密 Cookie/storage_state，
# 只通过 HTTP API 与后端通信，跳过校验（与 DATABASE_URL 一致）
if not _encryption_key and not _is_worker_process:
    raise ValueError(
        "AUTO_GEO_ENCRYPTION_KEY environment variable is required. "
        "Please set a 32-byte encryption key."
    )
ENCRYPTION_KEY = _encryption_key.encode()[:32] if _encryption_key else b''  # 纭繚鏄?2瀛楄妭

# ==================== JWT 认证配置 ====================
# 登录/鉴权使用的 JWT 签名密钥，生产环境必须设置
_jwt_secret = os.getenv("JWT_SECRET_KEY")
if not _jwt_secret and not _is_worker_process:
    raise ValueError(
        "JWT_SECRET_KEY environment variable is required. "
        "Please set a strong random secret in your .env file."
    )
JWT_SECRET_KEY = _jwt_secret
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

# ==================== Playwright閰嶇疆 ====================
# 閮ㄧ讲妯″紡锛歭ocal(鏈湴), cloud(浜戠), hybrid(娣峰悎)
DEPLOYMENT_MODE: Literal["local", "cloud", "hybrid"] = os.getenv(
    "DEPLOYMENT_MODE",
    "local",  # 榛樿鏈湴妯″紡
)

# 鏄惁鍚敤headless妯″紡锛堝彲閫氳繃鐜鍙橀噺瑕嗙洊
HEADLESS_MODE = os.getenv("HEADLESS_MODE", "false").lower() == "true"

# 鏈湴娴忚鍣–DP绔彛锛堢敤浜庢贩鍚堟灦鏋勶級
LOCAL_BROWSER_CDP_PORT = int(os.getenv("LOCAL_BROWSER_CDP_PORT", "9222"))

# 鏈湴娴忚鍣ㄥ叕缃戝湴鍧€锛堥€氳繃鍐呯綉绌块€忔毚闇诧級
# 鏍煎紡: http://xxxxx.xxx.io 鎴?http://IP:PORT
LOCAL_BROWSER_URL = os.getenv("LOCAL_BROWSER_URL", "")

# 鏄惁寮哄埗浣跨敤鏈湴娴忚鍣紙閫氳繃CDP杩炴帴
FORCE_LOCAL_BROWSER = os.getenv("FORCE_LOCAL_BROWSER", "false").lower() == "true"

# 娴忚鍣ㄧ被鍨
BROWSER_TYPE: Literal["chromium", "firefox", "webkit"] = "chromium"

# 娴忚鍣ㄥ惎鍔ㄥ弬鏁
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    # 绐楀彛灏哄鍜屼綅缃紙閫傞厤妗岄潰瀹㈡埛绔級
    "--window-size=1280,800",
    "--window-position=0,0",
    "--start-maximized",
    "--disable-gpu",  # 鍏煎 macOS 鍜岄儴鍒?Windows 鐜
    "--disable-dev-shm-usage",  # 閬垮厤瀹瑰櫒鐜鍐呭瓨涓嶈冻
    # 鎶戝埗銆屾仮澶嶄笂娆′細璇濄€嶆皵娉?    "--disable-session-crashed-bubble",
    "--disable-restore-session-state",
]

# 鎺堟潈娴忚鍣ㄧ獥鍙ｆā寮忥紙浠呬綔鍙傝€冿紝褰撳墠缁熶竴浣跨敤鐩存帴鎷夎捣鏈湴娴忚鍣級
AUTH_BROWSER_WINDOW_MODE = os.getenv("AUTH_BROWSER_WINDOW_MODE", "normal").strip().lower()

# 榛樿 User-Agent (淇濇寔缁熶竴锛岄槻姝?Session 鍥?UA 涓嶄竴鑷村け鏁?
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 鐢ㄦ埛鏁版嵁鐩綍
USER_DATA_DIR = DATA_DIR / "browser_context"

# 鐧诲綍妫€娴嬮厤缃
LOGIN_CHECK_INTERVAL = 1000  # 姣
LOGIN_MAX_WAIT_TIME = 120000  # 2鍒嗛挓

# ==================== 鍙戝竷瀹℃壒閰嶇疆锛圥hase 1锛氭湇鍔″櫒瀹℃壒寮忓彂甯冿級====================
#
# 璁捐鎬濊矾锛氬鎴风 exe 姣忎釜鍏抽敭鍙戝竷姝ラ閮介渶瑕佹湇鍔″櫒瀹℃壒锛屾湇鍔″櫒浣滀负鍞竴鍐崇瓥鑰呫€?# 涓€鍒囧彲浠ユ湰閰嶇疆鎺у埗锛氭€诲紑鍏炽€佹鏌ョ偣寮€鍏炽€佹潈闄愭牎楠屽紑鍏炽€佷护鐗岃繃鏈熸椂闂淬€佽皟璇曟梺璺€?#
# 鐜鍙橀噺瑕嗙洊绀轰緥锛?#   export PUBLISH_APPROVAL_ENABLED=false    # 鍏抽棴瀹℃壒
#   export PUBLISH_APPROVAL_TOKEN_TTL=600    # 浠ょ墝鏈夋晥鏈熸敼涓?10 鍒嗛挓
#   export PUBLISH_APPROVAL_BYPASS_USERS=1,2  # 鎸囧畾 user_id 璺宠繃瀹℃壒

_PUBLISH_APPROVAL_ENABLED_RAW = os.getenv("PUBLISH_APPROVAL_ENABLED", "true")
PUBLISH_APPROVAL_ENABLED = _PUBLISH_APPROVAL_ENABLED_RAW.lower() in {"1", "true", "yes", "on"}

# 鍚勬鏌ョ偣鐙珛寮€鍏筹細all=榛樿鍏ㄩ儴寮€鍚
PUBLISH_APPROVAL_CHECKPOINTS = {
    "before_write": os.getenv("PUBLISH_APPROVAL_CP_BEFORE_WRITE", "true").lower() in {"1", "true", "yes", "on"},
    "before_fill_body": os.getenv("PUBLISH_APPROVAL_CP_BEFORE_FILL_BODY", "true").lower() in {"1", "true", "yes", "on"},
    "before_submit": os.getenv("PUBLISH_APPROVAL_CP_BEFORE_SUBMIT", "true").lower() in {"1", "true", "yes", "on"},
}

# 鏉冮檺鏍￠獙鐙珛寮€鍏
PUBLISH_APPROVAL_PERMISSION_CHECKS = {
    "quota_check": os.getenv("PUBLISH_APPROVAL_CHECK_QUOTA", "true").lower() in {"1", "true", "yes", "on"},
    "platform_whitelist": os.getenv("PUBLISH_APPROVAL_CHECK_PLATFORM", "true").lower() in {"1", "true", "yes", "on"},
    "time_window": os.getenv("PUBLISH_APPROVAL_CHECK_TIME_WINDOW", "false").lower() in {"1", "true", "yes", "on"},
    "ip_check": os.getenv("PUBLISH_APPROVAL_CHECK_IP", "false").lower() in {"1", "true", "yes", "on"},
}

# 涓€娆℃€у鎵逛护鐗屾湁鏁堟湡锛堢
try:
    PUBLISH_APPROVAL_TOKEN_TTL = int(os.getenv("PUBLISH_APPROVAL_TOKEN_TTL", "300"))
except ValueError:
    PUBLISH_APPROVAL_TOKEN_TTL = 300

# 璋冭瘯鏃佽矾鍒楄〃锛堣皑鎱庝娇鐢級
# - bypass_user_ids: 璺宠繃瀹℃壒鐨勭敤鎴?ID锛堢敤浜庤繍钀ヨ皟璇?绱ф€ユ仮澶嶏級
# - auto_approve_devices: 鑷姩鍚屾剰鐨勮澶?ID锛堢敤浜庢寚瀹氱殑娴嬭瘯璁惧
_bypass_users_raw = os.getenv("PUBLISH_APPROVAL_BYPASS_USERS", "")
PUBLISH_APPROVAL_BYPASS_USER_IDS = set()
if _bypass_users_raw:
    for _u in _bypass_users_raw.split(","):
        _u = _u.strip()
        if _u.isdigit():
            PUBLISH_APPROVAL_BYPASS_USER_IDS.add(int(_u))

_auto_approve_devices_raw = os.getenv("PUBLISH_APPROVAL_AUTO_APPROVE_DEVICES", "")
PUBLISH_APPROVAL_AUTO_APPROVE_DEVICES = set()
if _auto_approve_devices_raw:
    for _d in _auto_approve_devices_raw.split(","):
        _d = _d.strip()
        if _d:
            PUBLISH_APPROVAL_AUTO_APPROVE_DEVICES.add(_d)

# 姹囨€讳负涓€涓父閲忓瓧鍏革紝鏂逛究璋冪敤鏂逛娇鐢
PUBLISH_APPROVAL_CONFIG = {
    "enabled": PUBLISH_APPROVAL_ENABLED,
    "checkpoints": PUBLISH_APPROVAL_CHECKPOINTS,
    "permission_checks": PUBLISH_APPROVAL_PERMISSION_CHECKS,
    "token_ttl_seconds": PUBLISH_APPROVAL_TOKEN_TTL,
    "bypass_user_ids": PUBLISH_APPROVAL_BYPASS_USER_IDS,
    "auto_approve_devices": PUBLISH_APPROVAL_AUTO_APPROVE_DEVICES,
}

# ==================== 平台配置 ====================
PLATFORMS = {
    "zhihu": {
        "id": "zhihu",
        "name": "知乎",
        "code": "ZH",
        "login_url": "https://www.zhihu.com/signin",
        "publish_url": "https://zhuanlan.zhihu.com/write",
        "color": "#0084FF",
    },
    "baijiahao": {
        "id": "baijiahao",
        "name": "百家号",
        "code": "BJH",
        "login_url": "https://baijiahao.baidu.com/builder/rc/static/login/index",
        "home_url": "https://baijiahao.baidu.com/builder/rc/static/edit/index",  # 鐧惧鍙烽椤碉紙浣滆€呬腑蹇冿級
        "publish_url": "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",  # 鍥炬枃缂栬緫鍣
        "color": "#E53935",
    },
    "sohu": {
        "id": "sohu",
        "name": "搜狐号",
        "code": "SOHU",
        "login_url": "https://mp.sohu.com/",
        # 鍚庡彴棣栭〉锛堝唴瀹圭鐞?firstpage锛夛細鐧诲綍鍚庤繘杩欓噷锛屽彂甯冨櫒鍐呭啀鐐?鍙戝竷鍐呭"杩涘浘鏂囩紪杈戝櫒
        "publish_url": "https://mp.sohu.com/mpfe/v4/contentManagement/firstpage",
        "color": "#FF6B00",
    },
    "toutiao": {
        "id": "toutiao",
        "name": "头条号",
        "code": "TT",
        "login_url": "https://mp.toutiao.com/",
        "publish_url": "https://mp.toutiao.com/profile_v4/graphic/publish",
        "color": "#333333",
    },
    "tieba": {
        "id": "tieba",
        "name": "百度贴吧",
        "code": "TB",
        "login_url": "https://tieba.baidu.com/",
        "home_url": "https://tieba.baidu.com/",
        "publish_url": "https://tieba.baidu.com/",
        "color": "#3388FF",
    },
    "wenku": {
        "id": "wenku",
        "name": "百度文库",
        "code": "WK",
        "login_url": "https://passport.baidu.com/v2/?login&tpl=wenku",
        "publish_url": "https://wenku.baidu.com/user/upload",
        "color": "#2932E1",
    },
    "penguin": {
        "id": "penguin",
        "name": "企鹅号",
        "code": "OM",
        "login_url": "https://om.qq.com/userAuth/index",
        "publish_url": "https://om.qq.com/article/articlePublish",
        "color": "#1E8AE8",
    },
    "weixin": {
        "id": "weixin",
        "name": "微信公众号",
        "code": "WX",
        "login_url": "https://mp.weixin.qq.com/",
        "home_url": "https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN",
        # 鑽夌绠卞叆鍙ｏ細瀵艰埅鍒拌繖閲屼細鑷姩甯?token锛岀劧鍚庣偣鍑?鍐欐柊鍥炬枃"杩涘叆缂栬緫鍣?        # 涓嶈兘鐩存帴杩?appmsg_edit锛屽洜涓哄畠闇€瑕?token 鍙傛暟纭紪鐮佷細澶辫触
        "publish_url": "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&lang=zh_CN",
        "color": "#07C160",
    },
    "wangyi": {
        "id": "wangyi",
        "name": "网易号",
        "code": "WY",
        "login_url": "https://mp.163.com/login.html",
        "publish_url": "https://mp.163.com/admin/article/publish",
        "color": "#E60026",
    },
    "zijie": {
        "id": "zijie",
        "name": "字节号",
        "code": "ZJ",
        "login_url": "https://mp.toutiao.com/",
        "publish_url": "https://mp.toutiao.com/profile/article/article_edit",
        "color": "#FA2A2D",
    },
    "xiaohongshu": {
        "id": "xiaohongshu",
        "name": "小红书",
        "code": "XHS",
        "login_url": "https://creator.xiaohongshu.com/login",
        "publish_url": "https://creator.xiaohongshu.com/publish/publish",
        "color": "#FF2442",
    },
    "bilibili": {
        "id": "bilibili",
        "name": "B站专栏",
        "code": "BL",
        "login_url": "https://passport.bilibili.com/login",
        "publish_url": "https://member.bilibili.com/platform/upload/text/new-article",
        "auto_generate_images": False,
        "inline_image_count": 0,
        "color": "#FB7299",
    },
    "36kr": {
        "id": "36kr",
        "name": "36氪",
        "code": "36KR",
        "login_url": "https://passport.36kr.com/mo/signin",
        "publish_url": "https://36kr.com/publish",
        "color": "#FF6A00",
    },
    "huxiu": {
        "id": "huxiu",
        "name": "虎嗅",
        "code": "HX",
        "login_url": "https://www.huxiu.com/passport/login",
        "publish_url": "https://www.huxiu.com/article/post",
        "color": "#FF9C41",
    },
    "woshipm": {
        "id": "woshipm",
        "name": "人人都是产品经理",
        "code": "PM",
        "login_url": "https://passport.woshipm.com/login",
        "publish_url": "https://www.woshipm.com/article/post",
        "color": "#2ECC71",
    },
    # 鏂板骞冲彴
    "douyin": {
        "id": "douyin",
        "name": "抖音",
        "code": "DY",
        "login_url": "https://creator.douyin.com/",
        "publish_url": "https://creator.douyin.com/creator-micro/content/upload",
        "color": "#000000",
    },
    "kuaishou": {
        "id": "kuaishou",
        "name": "快手",
        "code": "KS",
        "login_url": "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api&callback=https%3A%2F%2Fcp.kuaishou.com%2Frest%2Finfra%2Fsts%3FfollowUrl%3Dhttps%253A%252F%252Fcp.kuaishou.com%252Farticle%252Fpublish%252Fvideo%26setRootDomain%3Dtrue",
        "publish_url": "https://cp.kuaishou.com/article/publish/video",
        "color": "#FF4500",
    },
    "video_account": {
        "id": "video_account",
        "name": "视频号",
        "code": "WXV",
        "login_url": "https://channels.weixin.qq.com/",
        "publish_url": "https://channels.weixin.qq.com/post",
        "color": "#07C160",
    },
    "sohu_video": {
        "id": "sohu_video",
        "name": "搜狐视频",
        "code": "SHV",
        "login_url": "https://tv.sohu.com/",
        "publish_url": "https://tv.sohu.com/upload",
        "color": "#FF6B00",
    },
    "weibo": {
        "id": "weibo",
        "name": "新浪微博",
        "code": "WB",
        "login_url": "https://weibo.com/",
        "publish_url": "https://weibo.com/compose",
        "color": "#E6162D",
    },
    "haokan": {
        "id": "haokan",
        "name": "好看视频",
        "code": "HK",
        "login_url": "https://haokan.baidu.com/",
        "publish_url": "https://haokan.baidu.com/upload",
        "color": "#2932E1",
    },
    "xigua": {
        "id": "xigua",
        "name": "西瓜视频",
        "code": "XG",
        "login_url": "https://ixigua.com/",
        "publish_url": "https://ixigua.com/publish",
        "color": "#FA2A2D",
    },
    "jianshu": {
        "id": "jianshu",
        "name": "简书号",
        "code": "JS",
        "login_url": "https://www.jianshu.com/sign_in",
        "publish_url": "https://www.jianshu.com/writer",
        "color": "#EA6F5A",
    },
    "juejin": {
        "id": "juejin",
        "name": "掘金",
        "code": "JJ",
        "login_url": "https://juejin.cn/",
        "publish_url": "https://juejin.cn/editor/drafts/new",
        "color": "#1E80FF",
    },
    "iqiyi": {
        "id": "iqiyi",
        "name": "爱奇艺",
        "code": "IQY",
        "login_url": "https://www.iqiyi.com/",
        "publish_url": "https://mp.iqiyi.com/upload",
        "color": "#00BE06",
    },
    "dayu": {
        "id": "dayu",
        "name": "大鱼号",
        "code": "DYU",
        "login_url": "https://mp.dayu.com/",
        "publish_url": "https://mp.dayu.com/article/post",
        "color": "#FF6A00",
    },
    "acfun": {
        "id": "acfun",
        "name": "AcFun",
        "code": "AC",
        "login_url": "https://www.acfun.cn/login",
        "publish_url": "https://member.acfun.cn/article/publish",
        "color": "#FD4C5D",
    },
    "tencent_video": {
        "id": "tencent_video",
        "name": "腾讯视频",
        "code": "TXV",
        "login_url": "https://v.qq.com/",
        "publish_url": "https://upload.video.qq.com/",
        "color": "#FF6B00",
    },
    "yidian": {
        "id": "yidian",
        "name": "一点号",
        "code": "YD",
        "login_url": "https://mp.yidianzixun.com/",
        "publish_url": "https://mp.yidianzixun.com/publish",
        "color": "#007AFF",
    },
    "pipixia": {
        "id": "pipixia",
        "name": "皮皮虾",
        "code": "PPX",
        "login_url": "https://www.pipixia.com/",
        "publish_url": "https://www.pipixia.com/publish",
        "color": "#FF6900",
    },
    "meipai": {
        "id": "meipai",
        "name": "美拍",
        "code": "MP",
        "login_url": "https://www.meipai.com/",
        "publish_url": "https://www.meipai.com/publish",
        "color": "#1E88E5",
    },
    "douban": {
        "id": "douban",
        "name": "豆瓣",
        "code": "DB",
        "login_url": "https://www.douban.com/",
        "publish_url": "https://www.douban.com/note",
        "color": "#007722",
    },
    "csdn": {
        "id": "csdn",
        "name": "CSDN",
        "code": "CSDN",
        "login_url": "https://passport.csdn.net/login",
        "home_url": "https://mp.csdn.net/",  # 鍒涗綔涓績棣栭〉锛堢櫥褰曟€佸仴搴锋鏌ヨ闂級
        "publish_url": "https://mp.csdn.net/console/editor/html",  # 鍐欏崥瀹㈢紪杈戝櫒
        "color": "#FC5531",
    },
    "cnblogs": {
        "id": "cnblogs",
        "name": "博客园",
        "code": "CNB",
        "login_url": "https://account.cnblogs.com/signin",
        "home_url": "https://i.cnblogs.com/",  # 鍚庡彴棣栭〉锛堢櫥褰曟€佸仴搴锋鏌ヨ闂級
        "publish_url": "https://i.cnblogs.com/EditPosts.aspx",  # 鍙戝崥缂栬緫鍣?        "color": "#2A6E3F",
    },
    "kuai_chuan": {
        "id": "kuai_chuan",
        "name": "快传号",
        "code": "KC",
        "login_url": "https://kuai.360.cn/",
        "publish_url": "https://kuai.360.cn/publish",
        "color": "#00BE3B",
    },
    "dafeng": {
        "id": "dafeng",
        "name": "大风号",
        "code": "DF",
        "login_url": "https://mp.ifeng.com/",
        "publish_url": "https://mp.ifeng.com/article/post",
        "color": "#DD2E1B",
    },
    "xueqiu": {
        "id": "xueqiu",
        "name": "雪球号",
        "code": "XQ",
        "login_url": "https://xueqiu.com/",
        "publish_url": "https://xueqiu.com/post",
        "color": "#2775CA",
    },
    "yiche": {
        "id": "yiche",
        "name": "易车号",
        "code": "YC",
        "login_url": "https://mp.yiche.com/",
        "publish_url": "https://mp.yiche.com/article/post",
        "color": "#FF6600",
    },
    "chejia": {
        "id": "chejia",
        "name": "车家号",
        "code": "CJ",
        "login_url": "https://mp.autohome.com.cn/",
        "publish_url": "https://mp.autohome.com.cn/article/post",
        "color": "#E60012",
    },
    "duoduo": {
        "id": "duoduo",
        "name": "多多视频",
        "code": "DD",
        "login_url": "https://mp.pinduoduo.com/",
        "publish_url": "https://mp.pinduoduo.com/publish",
        "color": "#E02E24",
    },
    "weishi": {
        "id": "weishi",
        "name": "腾讯微视",
        "code": "WS",
        "login_url": "https://weishi.qq.com/",
        "publish_url": "https://weishi.qq.com/publish",
        "color": "#FF6B00",
    },
    "mango": {
        "id": "mango",
        "name": "芒果TV",
        "code": "MG",
        "login_url": "https://www.mgtv.com/",
        "publish_url": "https://www.mgtv.com/upload",
        "color": "#FF7F00",
    },
    "ximalaya": {
        "id": "ximalaya",
        "name": "喜马拉雅",
        "code": "XMLY",
        "login_url": "https://www.ximalaya.com/",
        "publish_url": "https://www.ximalaya.com/upload",
        "color": "#F84438",
    },
    "meituan": {
        "id": "meituan",
        "name": "美团",
        "code": "MT",
        "login_url": "https://meituan.com/",
        "publish_url": "https://meituan.com/publish",
        "color": "#FFBC00",
    },
    "alipay": {
        "id": "alipay",
        "name": "支付宝",
        "code": "ZFB",
        "login_url": "https://open.alipay.com/",
        "publish_url": "https://open.alipay.com/publish",
        "color": "#1677FF",
    },
    "douyin_company": {
        "id": "douyin_company",
        "name": "抖音企业号",
        "code": "DYC",
        "login_url": "https://business.douyin.com/",
        "publish_url": "https://business.douyin.com/publish",
        "color": "#000000",
    },
    "douyin_company_lead": {
        "id": "douyin_company_lead",
        "name": "抖音企业号（线索版）",
        "code": "DYL",
        "login_url": "https://business.douyin.com/",
        "publish_url": "https://business.douyin.com/publish",
        "color": "#000000",
    },
    "custom": {
        "id": "custom",
        "name": "自定义",
        "code": "CUSTOM",
        "login_url": "",
        "publish_url": "",
        "color": "#999999",
    },
    # AI 平台：账号管理中可绑定，用于 GEO 测评；不具备文章发布能力。
    "doubao": {
        "id": "doubao",
        "name": "豆包",
        "code": "DBO",
        "login_url": "https://www.doubao.com",
        "publish_url": "",
        "color": "#0066FF",
    },
    "qianwen": {
        "id": "qianwen",
        "name": "通义千问",
        "code": "QW",
        "login_url": "https://qianwen.com/?source=tongyiqw",
        "publish_url": "",
        "color": "#FF6A00",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "code": "DS",
        "login_url": "https://chat.deepseek.com",
        "publish_url": "",
        "color": "#4D6BFE",
    },
}

# ==================== 日志配置 ====================
# 按天滚动：文件名带日期后缀（{time:YYYY-MM-DD} 由 loguru 在打开文件时替换为当天日期），
# 每天午夜（00:00）轮转新开一个文件；同一天追加写入，进程重启也并入同一个当天文件。
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = str(LOG_DIR / "auto_geo_{time:YYYY-MM-DD}.log")  # 如 auto_geo_2025-01-15.log
ERROR_LOG_FILE = str(LOG_DIR / "auto_geo_error_{time:YYYY-MM-DD}.log")  # 仅 WARNING+，快速排障
# GEO 测评 worker（独立进程）专用日志文件：其 stdout 承载 JSON 事件协议，日志只落文件
WORKER_LOG_FILE = str(LOG_DIR / "auto_geo_worker_{time:YYYY-MM-DD}.log")
WORKER_ERROR_LOG_FILE = str(LOG_DIR / "auto_geo_worker_error_{time:YYYY-MM-DD}.log")
LOG_ROTATION = "00:00"  # 每天午夜新开一个文件
LOG_RETENTION = "3 days"  # 主日志只保留最近 3 天（loguru 轮转时自动清理）
LOG_ERROR_RETENTION = "3 days"  # 错误日志只保留最近 3 天
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))  # 启动清扫兜底（单位：天）
# 控制台日志级别（默认 INFO；排障时设 LOG_LEVEL=DEBUG 看全量）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# 主日志文件级别（默认 DEBUG，全面留底；按天滚动）
LOG_FILE_LEVEL = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()
# 错误日志文件级别（默认 WARNING；独立文件按天滚动）
LOG_ERROR_LEVEL = os.getenv("LOG_ERROR_LEVEL", "WARNING").upper()
# 标准库 logging -> loguru 桥接级别（第三方库日志默认只收 INFO 及以上，避免 DEBUG 噪音）
LOG_STDLIB_BRIDGE_LEVEL = os.getenv("LOG_STDLIB_BRIDGE_LEVEL", "INFO").upper()

LOG_DIR.mkdir(exist_ok=True)

# ==================== 浠诲姟閰嶇疆 ====================
# 鍙戝竷浠诲姟瓒呮椂鏃堕棿锛堢
PUBLISH_TIMEOUT = 300

# 鏈€澶у苟鍙戝彂甯冩暟
MAX_CONCURRENT_PUBLISH = 3

# 澶辫触閲嶈瘯娆℃暟
MAX_RETRY_COUNT = 2

# 閲嶈瘯闂撮殧锛堢
RETRY_INTERVAL = 5

# ==================== DeepSeek API 配置 ====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")

# ==================== 鐏北鏂硅垷锛圖eepSeek 鑱旂綉鎼滅储鐗堬級====================
# 鐏北鏂硅垷鎺у埗鍙帮細https://www.volcengine.com/product/ark
# 鍒涘缓銆孌eepSeek-R1-鑱旂綉鎼滅储鐗堛€嶆帴鍏ョ偣锛屽紑鍚€岃仈缃戝唴瀹规彃浠躲€
VOLCENGINE_ARK_API_KEY = os.getenv("VOLCENGINE_ARK_API_KEY", "")
VOLCENGINE_ARK_BASE_URL = os.getenv("VOLCENGINE_ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
# 鎺ュ叆鐐?ID锛堜粠鐏北鏂硅垷鎺у埗鍙拌幏鍙栵級
# DeepSeek-R1 鑱旂綉鎼滅储鐗堬紙鍐呯疆鑱旂綉鎼滅储锛屾棤闇€ plugins 鍙傛暟
VOLCENGINE_ARK_DEEPSEEK_ENDPOINT = os.getenv(
    "VOLCENGINE_ARK_DEEPSEEK_ENDPOINT",
    os.getenv("VOLCENGINE_ARK_ENDPOINT", "deepseek-r1"),
)
# 璞嗗寘妯″瀷锛堥€氳繃 ARK API 璋冪敤锛屽惎鐢ㄨ仈缃戞悳绱㈡彃浠讹級
VOLCENGINE_ARK_DOUBAO_ENDPOINT = os.getenv("VOLCENGINE_ARK_DOUBAO_ENDPOINT", "doubao-seed-1.6")
# GEO 鏀跺綍娴嬭瘎浣跨敤鐨?API 骞冲彴鍒楄〃
GEO_EVALUATION_API_PLATFORMS = [
    p.strip()
    for p in os.getenv("GEO_EVALUATION_API_PLATFORMS", "doubao,deepseek").split(",")
    if p.strip()
]

# 鍚庡彴鏅鸿兘浣撳ぇ妯″瀷瑙ｆ瀽寮€鍏?# 榛樿寮€鍚細鎰忓浘/鍏抽敭璇嶈瘑鍒€佸瓧娈垫娊鍙栥€佹憳瑕佷紭鍏堣蛋 LLM锛堟洿鐏垫椿锛岃兘澶勭悊銆屾瘡涓」鐩彂15涓枃绔犮€?# 杩欑被瑙勫垯闅捐鐩栫殑鑷劧璇█锛夈€傛棤 API key 鏃?_llm_enabled() 杩斿洖 False锛屽叏绋嬩紭闆呭洖閫€鍒拌鍒欒矾鐢憋紝
# 鍥犳鍗充娇鏈厤缃?key 涔熶笉浼氭姤閿欍€傝涓?false 鍙己鍒剁函瑙勫垯銆
AUTOGEO_CONVERSATION_USE_LLM = os.getenv("AUTOGEO_CONVERSATION_USE_LLM", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
AUTOGEO_CONVERSATION_LLM_PROVIDER = os.getenv("AUTOGEO_CONVERSATION_LLM_PROVIDER", "deepseek")
AUTOGEO_CONVERSATION_LLM_API_KEY = os.getenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "")
AUTOGEO_CONVERSATION_LLM_BASE_URL = os.getenv(
    "AUTOGEO_CONVERSATION_LLM_BASE_URL",
    os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1"),
)
AUTOGEO_CONVERSATION_LLM_MODEL = os.getenv(
    "AUTOGEO_CONVERSATION_LLM_MODEL",
    os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
)

# ==================== RAGFlow 閰嶇疆 ====================
# RAGFlow 鏈嶅姟鍦板潃
RAGFLOW_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "https://ragflow.xinzhixietong.com")
# RAGFlow API Key - 鐢熶骇鐜蹇呴』浠庣幆澧冨彉閲忚鍙
RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY")
# worker 进程不需要 RAGFlow（只跑 Playwright + HTTP 回传），跳过校验
if not RAGFLOW_API_KEY and not _is_worker_process:
    raise ValueError(
        "RAGFLOW_API_KEY environment variable is required. "
        "Please set your RAGFlow API key."
    )
# RAGFlow 鐭ヨ瘑搴揑D锛堢敤浜庡瓨鍌ㄩ噰闆嗙殑鏂囩珷
RAGFLOW_DATASET_ID = os.getenv("RAGFLOW_DATASET_ID", "dff2935cfc2011f0b36f0e3309b7ec55")
# RAGFlow 鐭ヨ瘑搴撳悕绉帮紙鑷姩鍒涘缓鏃朵娇鐢級
RAGFLOW_DATASET_NAME = os.getenv("RAGFLOW_DATASET_NAME", "reference_articles_kb")
# RAGFlow 鐭ヨ瘑搴撹В鏋愪娇鐢ㄧ殑鍚戦噺妯″瀷锛涗负绌烘椂瀹㈡埛绔細灏濊瘯澶嶇敤宸叉湁鐭ヨ瘑搴撶殑妯″瀷
RAGFLOW_EMBEDDING_MODEL = os.getenv("RAGFLOW_EMBEDDING_MODEL", "text-embedding-v4@Tongyi-Qianwen")
# 鍘婚噸鐩镐技搴﹂槇鍊
RAGFLOW_DUPLICATE_THRESHOLD = float(os.getenv("RAGFLOW_DUPLICATE_THRESHOLD", "0.85"))
# 妫€绱㈣繑鍥炴暟閲
RAGFLOW_TOP_K = int(os.getenv("RAGFLOW_TOP_K", "50"))
# 妫€绱㈢浉浼煎害闃堝€
RAGFLOW_SIMILARITY_THRESHOLD = float(os.getenv("RAGFLOW_SIMILARITY_THRESHOLD", "0.7"))
# 鍚屾绛栫暐锛歭ocal_to_ragflow, ragflow_to_local, bidirectional
RAGFLOW_SYNC_STRATEGY = os.getenv("RAGFLOW_SYNC_STRATEGY", "local_to_ragflow")

# ==================== AI骞冲彴妫€娴嬮厤缃?====================
# 鏀跺綍妫€娴嬬殑AI骞冲彴鍒楄〃
AI_PLATFORMS = {
    "doubao": {
        "id": "doubao",
        "name": "豆包",
        "url": "https://www.doubao.com",
        "login_url": "https://www.doubao.com/chat",
        "key_cookie": "sessionid|s_v_web_id|passport_csrf_token",
        "login_redirect": "passport.doubao.com|login.doubao.com|passport.bytedance.com",
        "color": "#0066FF",
    },
    "qianwen": {
        "id": "qianwen",
        "name": "通义千问",
        "url": "https://qianwen.com/?source=tongyiqw",
        "login_url": "https://qianwen.com/?source=tongyiqw",
        "key_cookie": "cna|login_aliyunid|isg",
        "login_redirect": "login.aliyun.com|signin.aliyun.com|passport.aliyun.com",
        "color": "#FF6A00",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "url": "https://chat.deepseek.com",
        "login_url": "https://chat.deepseek.com",
        "key_cookie": "sessionid|ds_session|auth_token",
        "login_redirect": "chat.deepseek.com/sign_in|deepseek.com/login",
        "color": "#4D6BFE",
    },
}

# 鏀跺綍妫€娴嬪畾鏃朵换鍔￠厤缃
INDEX_CHECK_HOUR = 2  # 姣忓ぉ鍑屾櫒2鐐规墽琛
INDEX_CHECK_MINUTE = 0

# ==================== AdsPower 鎸囩汗娴忚鍣?====================
ADSPOWER_API_URL = os.getenv("ADSPOWER_API_URL", "http://local.adspower.net:50325")
ADSPOWER_ENABLED = os.getenv("ADSPOWER_ENABLED", "false").lower() == "true"

# ==================== 椋炰功閰嶇疆 ====================
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
FEISHU_ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")
AUTOGEO_AGENT_TOKEN = os.getenv("AUTOGEO_AGENT_TOKEN", "")
FEISHU_BOT_NAME = os.getenv("FEISHU_BOT_NAME", "AutoGeo鍔╂墜")
