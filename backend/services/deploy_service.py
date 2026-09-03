import mimetypes
import os
import re
import socket
import io
from pathlib import Path
import logging

import httpx
import paramiko
import boto3
from boto3.exceptions import Boto3Error
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("deploy")


class DeployError(Exception):
    """携带结构化 detail 的发布失败异常。

    所有可预见的发布失败都应抛出 DeployError，由 api 层映射成结构化 HTTP 响应，
    而不是被全局 exception_handler 统一包装成泛化 500。
    """

    def __init__(self, code: str, message: str, suggestion: str = "", status: int = 400):
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.status = status
        super().__init__(message)


# .html/.css/.js 必须带 charset，并显式 inline，否则浏览器会下载而非渲染
_CONTENT_TYPE_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class DeployService:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.sites_dir = self.base_dir / "static" / "sites"

    # ==================== 通用辅助 ====================

    def _get_site_path(self, site_id: str):
        path = self.sites_dir / site_id
        if not path.exists():
            raise DeployError(
                code="SITE_NOT_FOUND",
                message="站点预览已失效，请重新生成。",
                suggestion="返回编辑器重新生成预览后再发布。",
                status=404,
            )
        return path

    def _sanitize_name(self, name: str):
        """项目名 → 安全目录片段；中文/特殊字符全过滤后返回空串（由调用方兜底 site_id）。"""
        if not name:
            return ""
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", name).lower()
        return re.sub(r"_+", "_", safe_name).strip("_")

    def _make_folder_name(self, project_name: str, site_id: str, publish_slug: str = "") -> str:
        """发布目录名：自定义 slug 优先，否则 项目slug-site_id[:8]，永远带 site_id 后缀防重名覆盖。"""
        if publish_slug:
            slug = self._sanitize_name(publish_slug) or site_id[:8]
        else:
            slug = self._sanitize_name(project_name) or site_id[:8]
        return f"{slug}-{site_id[:8]}"

    def _content_type_for(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in _CONTENT_TYPE_OVERRIDES:
            return _CONTENT_TYPE_OVERRIDES[ext]
        return mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    def _build_public_url(self, base: str, folder_name: str, entry: str = "index.html") -> str:
        """统一拼接浏览器访问 URL：去掉 base 末尾斜杠，永远指向 index.html。"""
        return f"{base.rstrip('/')}/{folder_name}/{entry}"

    def _ensure_remote_dir(self, sftp, remote_dir: str):
        """递归创建远程目录 —— 任意中间层级缺失都自动补齐（原 _upload_dir 只建当前层）。"""
        parts = [p for p in remote_dir.strip("/").split("/") if p]
        current = ""
        for part in parts:
            current += f"/{part}"
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)

    def _verify_url(self, url: str) -> dict:
        """发布后非阻断访问检测。

        返回 {"ok": bool, "warning": str|None, "suggestion": str|None}。
        任何网络问题都归为 ok=False + warning，绝不抛异常 —— 内网/防火墙/CDN 未生效
        不应误判为发布失败而阻断返回已上传的 URL。
        """
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(url)
        except Exception as e:  # 超时 / DNS / 连接拒绝 —— 全部降级为 warning
            logger.warning(f"verify_url unreachable {url}: {e}")
            return {
                "ok": False,
                "warning": "文件已上传，但访问 URL 暂时无法打开。",
                "suggestion": "请检查 public_base_url、Nginx root、域名解析与防火墙。",
            }

        if resp.status_code != 200:
            return {
                "ok": False,
                "warning": f"文件已上传，但访问 URL 返回 HTTP {resp.status_code}。",
                "suggestion": "请确认 Nginx root 与上传路径一致、域名解析正确。",
            }

        disposition = resp.headers.get("content-disposition", "")
        if "attachment" in disposition.lower():
            # 阿里云/腾讯云/华为云等对象存储：用默认域名访问网页类文件会被平台强制加
            # Content-Disposition: attachment（安全策略，无法用上传时的 inline 覆盖）。
            # 此时只能绑定自定义域名/CDN + 开启静态网站托管才能在线打开。
            if any(d in url for d in ("aliyuncs.com", "myqcloud.com", "myhuaweicloud.com")):
                return {
                    "ok": False,
                    "warning": "对象存储默认域名访问网页会被浏览器强制下载。",
                    "suggestion": "请在 OSS/COS 控制台绑定已备案的自定义域名（或 CDN）并开启静态网站托管，再在「访问域名」里填该域名重新发布。",
                }
            return {
                "ok": False,
                "warning": "服务器返回 Content-Disposition: attachment，浏览器会下载而非打开网页。",
                "suggestion": "请将 Nginx/Apache 响应头改为 inline，或移除 attachment。",
            }

        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype.lower():
            return {
                "ok": False,
                "warning": f"返回内容类型为 {ctype or '未知'}，浏览器可能无法正常渲染。",
                "suggestion": "请确认服务器以 text/html 提供 index.html。",
            }

        return {"ok": True, "warning": None, "suggestion": None}

    def _count_files(self, local_path: Path) -> int:
        return sum(len(files) for _, _, files in os.walk(local_path))

    def _load_private_key(self, private_key: str, passphrase: str = None):
        if not private_key:
            return None

        key_text = private_key.strip().lstrip("\ufeff")
        # Some copy paths paste JSON-style escaped newlines into the textarea.
        if "\\n" in key_text and "\n" not in key_text:
            key_text = key_text.replace("\\r\\n", "\n").replace("\\n", "\n")
        key_text = key_text.replace("\r\n", "\n").replace("\r", "\n").strip()

        match = re.search(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            key_text,
            flags=re.DOTALL,
        )
        if match:
            key_text = match.group(0).strip()

        header = key_text.splitlines()[0] if key_text else ""
        if "BEGIN" not in header or "PRIVATE KEY" not in header:
            raise DeployError(
                code="SFTP_INVALID_PRIVATE_KEY",
                message="无法解析 SSH 私钥。",
                suggestion="请粘贴 .pem 私钥完整内容，第一行应类似 -----BEGIN OPENSSH PRIVATE KEY----- 或 -----BEGIN RSA PRIVATE KEY-----。",
                status=400,
            )

        key_errors = []
        key_classes = (
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
            paramiko.DSSKey,
        )
        for key_class in key_classes:
            try:
                return key_class.from_private_key(io.StringIO(key_text), password=passphrase or None)
            except paramiko.PasswordRequiredException:
                raise DeployError(
                    code="SFTP_KEY_PASSPHRASE_REQUIRED",
                    message="私钥需要口令。",
                    suggestion="请填写 PEM 私钥对应的 passphrase，或改用无口令私钥。",
                    status=400,
                )
            except paramiko.SSHException as e:
                key_errors.append(str(e))

        raise DeployError(
            code="SFTP_INVALID_PRIVATE_KEY",
            message="无法解析 SSH 私钥。",
            suggestion=f"已识别到 {header or '未知头部'}，但当前运行环境无法解析。请确认它不是 .ppk 文件或公钥；如本机可 ssh 登录，可执行 ssh-keygen -p -m PEM -f 原私钥 转成 PEM 后再粘贴。",
            status=400,
        )

    # ==================== SFTP ====================

    def deploy_sftp(
        self,
        site_id: str,
        project_name: str,
        host: str,
        port: int,
        username: str,
        remote_root: str,
        auth_type: str = "password",
        password: str = None,
        private_key: str = None,
        key_passphrase: str = None,
        custom_domain: str = None,
        public_base_url: str = None,
        publish_slug: str = "",
    ):
        local_path = self._get_site_path(site_id)
        folder_name = self._make_folder_name(project_name, site_id, publish_slug)
        target_remote_dir = f"{remote_root.rstrip('/')}/{folder_name}"
        uploaded = self._count_files(local_path)
        auth_type = auth_type or ("private_key" if private_key else "password")

        transport = None
        try:
            pkey = self._load_private_key(private_key, key_passphrase) if auth_type == "private_key" else None
            transport = paramiko.Transport((host, int(port)))
            transport.banner_timeout = 30
            transport.connect(
                username=username,
                password=password if auth_type == "password" else None,
                pkey=pkey,
            )
            sftp = paramiko.SFTPClient.from_transport(transport)

            def _upload_dir(local_dir, remote_dir):
                self._ensure_remote_dir(sftp, remote_dir)
                try:
                    sftp.chmod(remote_dir, 0o755)
                except OSError:
                    pass  # 某些服务器不允许 chmod，忽略
                for item in os.listdir(local_dir):
                    l_path = os.path.join(local_dir, item)
                    r_path = f"{remote_dir}/{item}".replace("//", "/")
                    if os.path.isfile(l_path):
                        sftp.put(l_path, r_path)
                        try:
                            sftp.chmod(r_path, 0o644)
                        except OSError:
                            pass
                    elif os.path.isdir(l_path):
                        _upload_dir(l_path, r_path)

            _upload_dir(str(local_path), target_remote_dir)
            sftp.close()
            transport.close()
            transport = None
        except paramiko.AuthenticationException:
            raise DeployError(
                code="SFTP_AUTH_FAILED",
                message="SFTP 用户名、密码或私钥无效。",
                suggestion="请检查 SSH 用户名、密码/私钥，以及该公钥是否已加入服务器 authorized_keys。",
                status=400,
            )
        except (paramiko.SSHException, socket.error, EOFError) as e:
            # SSHException 既可能是连接失败也可能是权限问题，按文本细分
            msg = str(e).lower()
            if "permission" in msg:
                raise DeployError(
                    code="SFTP_PERMISSION_DENIED",
                    message="远程上传目录没有写权限。",
                    suggestion="请确认 SFTP 用户可写入该目录，或改用有权限的上传路径。",
                    status=403,
                )
            raise DeployError(
                code="SFTP_CONNECT_FAILED",
                message="无法连接远程服务器。",
                suggestion="请检查主机 IP、端口、防火墙与 SSH 服务是否运行。",
                status=502,
            )
        except PermissionError:
            raise DeployError(
                code="SFTP_PERMISSION_DENIED",
                message="远程上传目录没有写权限。",
                suggestion="请确认 SFTP 用户可写入该目录，或改用有权限的上传路径。",
                status=403,
            )
        except DeployError:
            raise
        except Exception as e:
            logger.error(f"SFTP unexpected error: {e}", exc_info=True)
            raise DeployError(
                code="SFTP_DEPLOY_FAILED",
                message="发布失败，请查看后端日志。",
                suggestion=str(e),
                status=500,
            )
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass

        # URL 优先级：public_base_url → 旧 custom_domain → 兜底 http://{host}
        base = public_base_url or custom_domain or f"http://{host}"
        public_url = self._build_public_url(base, folder_name)

        verify = self._verify_url(public_url)
        return {
            "status": "success",
            "method": "sftp",
            "url": public_url,
            "entry": "index.html",
            "uploaded_files": uploaded,
            "target_path": target_remote_dir,
            "message": "发布成功",
            "warning": verify["warning"],
            "suggestion": verify["suggestion"],
        }

    # ==================== OSS / S3 ====================

    def deploy_s3(
        self,
        site_id: str,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = None,
        public_base_url: str = None,
    ):
        local_path = self._get_site_path(site_id)

        s3_config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
        }
        if endpoint:
            s3_config["endpoint_url"] = endpoint
        if region:
            s3_config["region_name"] = region

        # 阿里云 OSS 等使用 path-style 访问会报 SecondLevelDomainForbidden /
        # "Please use virtual hosted style to access"，必须强制 virtual-hosted 寻址。
        # endpoint 应为区域级（如 https://oss-cn-hangzhou.aliyuncs.com），不要带 bucket。
        if endpoint and "aliyuncs" in endpoint:
            s3_config["config"] = Config(s3={"addressing_style": "virtual"})

        try:
            s3 = boto3.client("s3", **s3_config)
        except (BotoCoreError, Boto3Error) as e:
            raise DeployError(
                code="OSS_CLIENT_INIT_FAILED",
                message="OSS 客户端初始化失败。",
                suggestion=str(e),
                status=400,
            )

        uploaded = 0
        try:
            for root, _dirs, files in os.walk(local_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, local_path).replace("\\", "/")
                    extra_args = {
                        "ContentType": self._content_type_for(full_path),
                        "ContentDisposition": "inline",
                    }

                    try:
                        s3.upload_file(
                            Filename=full_path,
                            Bucket=bucket,
                            Key=relative_path,
                            ExtraArgs=extra_args,
                        )
                        uploaded += 1
                    except ClientError as e:
                        code = e.response.get("Error", {}).get("Code", "")
                        if code == "AccessDenied":
                            raise DeployError(
                                code="OSS_ACCESS_DENIED",
                                message="OSS 拒绝访问（权限不足）。",
                                suggestion="请确认 Bucket 已开启公共读，或 AccessKey 有写入该 Bucket 的权限。",
                                status=403,
                            )
                        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch"):
                            raise DeployError(
                                code="OSS_INVALID_CREDENTIALS",
                                message="OSS 凭证无效。",
                                suggestion="请检查 AccessKey 与 SecretKey。",
                                status=401,
                            )
                        if code in ("NoSuchBucket",):
                            raise DeployError(
                                code="OSS_BUCKET_MISMATCH",
                                message="Bucket 不存在或与 Endpoint 区域不匹配。",
                                suggestion="请确认 Bucket 名称正确，且 Endpoint 区域与 Bucket 一致。",
                                status=400,
                            )
                        logger.error(f"OSS upload ClientError: {e}", exc_info=True)
                        raise DeployError(
                            code="OSS_UPLOAD_FAILED",
                            message="对象上传失败。",
                            suggestion=str(e),
                            status=400,
                        )
                    except (BotoCoreError, Boto3Error) as e:
                        msg = str(e).lower()
                        if any(k in msg for k in ("connection", "endpoint", "resolve", "timeout")):
                            raise DeployError(
                                code="OSS_CONNECT_FAILED",
                                message="无法连接 OSS Endpoint。",
                                suggestion="请检查 Endpoint、网络与 DNS。",
                                status=502,
                            )
                        logger.error(f"OSS upload error: {e}", exc_info=True)
                        raise DeployError(
                            code="OSS_UPLOAD_FAILED",
                            message="对象上传失败。",
                            suggestion=str(e),
                            status=400,
                        )
        except DeployError:
            raise
        except Exception as e:
            logger.error(f"S3 unexpected error: {e}", exc_info=True)
            raise DeployError(
                code="OSS_DEPLOY_FAILED",
                message="发布失败，请查看后端日志。",
                suggestion=str(e),
                status=500,
            )

        # URL 优先级：用户填的 public_base_url → 阿里云 virtual-hosted 域名 → 通用 endpoint/bucket
        # OSS 对象直接放 bucket 根（与站点目录一一对应），无需子目录。
        if public_base_url:
            public_url = f"{public_base_url.rstrip('/')}/index.html"
        elif endpoint and "aliyuncs" in endpoint:
            host = endpoint.split("//", 1)[1].rstrip("/")
            public_url = f"https://{bucket}.{host}/index.html"
        else:
            ep = (endpoint or "").rstrip("/")
            public_url = f"{ep}/{bucket}/index.html"

        verify = self._verify_url(public_url)
        return {
            "status": "success",
            "method": "s3",
            "url": public_url,
            "entry": "index.html",
            "uploaded_files": uploaded,
            "target_path": f"{bucket}/",
            "message": "发布成功",
            "warning": verify["warning"],
            "suggestion": verify["suggestion"],
        }
