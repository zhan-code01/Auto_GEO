#!/usr/bin/env python3
"""Publish an AutoGeo site-builder project with optional remote Nginx setup.

Examples:
  python scripts/site_builder_publish.py \
    --api-base http://127.0.0.1:8001/api \
    --token "$AUTOGEO_TOKEN" \
    --site-id abc123 \
    --project-name demo \
    --sftp-host 1.2.3.4 \
    --sftp-user root \
    --sftp-path /var/www/html \
    --public-base-url https://www.example.com \
    --configure-nginx \
    --server-name www.example.com
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import posixpath
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_MIME_TYPES = """
    types {
        text/html html htm;
        text/css css;
        application/javascript js mjs;
        image/png png;
        image/jpeg jpg jpeg;
        image/svg+xml svg;
        image/webp webp;
        image/gif gif;
        font/woff woff;
        font/woff2 woff2;
    }
""".rstrip()


@dataclass
class NginxConfig:
    host: str
    port: int
    username: str
    password: str | None
    private_key_path: str | None
    key_passphrase: str | None
    web_root: str
    server_name: str
    conf_path: str
    reload_command: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure static Nginx hosting and publish an AutoGeo site-builder project.",
    )
    parser.add_argument("--config", help="JSON config file with fixed publish parameters")
    parser.add_argument("--api-base", help="AutoGeo API base, for example http://host:8001/api")
    parser.add_argument("--token", default=os.getenv("AUTOGEO_TOKEN"), help="Bearer token, or AUTOGEO_TOKEN")
    parser.add_argument("--site-id", help="Generated site_id from AutoGeo")
    parser.add_argument("--project-name", help="Project name used by AutoGeo to build the folder name")
    parser.add_argument("--publish-slug", default="", help="Optional public folder slug")

    parser.add_argument("--method", choices=("sftp", "s3"), default="sftp")
    parser.add_argument("--public-base-url", help="Public URL prefix, for example https://www.example.com")

    parser.add_argument("--sftp-host", help="SFTP/SSH host")
    parser.add_argument("--sftp-port", type=int, default=22)
    parser.add_argument("--sftp-user", help="SFTP/SSH username")
    parser.add_argument("--sftp-password", default=os.getenv("SFTP_PASSWORD"), help="SFTP password, or SFTP_PASSWORD")
    parser.add_argument("--sftp-private-key-file", help="Path to a PEM/OpenSSH private key")
    parser.add_argument("--sftp-key-passphrase", default=os.getenv("SFTP_KEY_PASSPHRASE"))
    parser.add_argument("--sftp-path", default="/var/www/html", help="Remote web root visible to Nginx")

    parser.add_argument("--s3-endpoint")
    parser.add_argument("--s3-bucket")
    parser.add_argument("--s3-access-key", default=os.getenv("S3_ACCESS_KEY"))
    parser.add_argument("--s3-secret-key", default=os.getenv("S3_SECRET_KEY"))

    parser.add_argument(
        "--configure-nginx",
        action="store_true",
        help="Before publishing, create/update a remote Nginx static-site server block over SSH.",
    )
    parser.add_argument("--server-name", help="Nginx server_name. Defaults to host part of --public-base-url.")
    parser.add_argument("--nginx-conf-path", default="/etc/nginx/conf.d/autogeo-sites.conf")
    parser.add_argument("--nginx-reload-command", default="nginx -t && nginx -s reload")

    return parser.parse_args()


def apply_config(args: argparse.Namespace) -> argparse.Namespace:
    if not args.config:
        return args

    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    if not isinstance(config, dict):
        raise SystemExit("--config must point to a JSON object")

    for key, value in config.items():
        dest = key.replace("-", "_")
        if not hasattr(args, dest):
            continue
        current = getattr(args, dest)
        if current in (None, ""):
            setattr(args, dest, value)

    return args


def require(value: str | None, label: str) -> str:
    if not value:
        raise SystemExit(f"Missing required parameter: {label}")
    return value


def host_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit("--public-base-url must be a full http:// or https:// URL")
    return parsed.netloc.split(":", 1)[0]


def private_key_text(path: str | None) -> str | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def auth_type(args: argparse.Namespace) -> str:
    return "private_key" if args.sftp_private_key_file else "password"


def build_deploy_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "site_id": args.site_id,
        "project_name": args.project_name,
        "method": args.method,
        "public_base_url": args.public_base_url,
    }

    if args.method == "sftp":
        payload.update(
            {
                "sftp_host": require(args.sftp_host, "--sftp-host"),
                "sftp_port": args.sftp_port,
                "sftp_user": require(args.sftp_user, "--sftp-user"),
                "sftp_auth_type": auth_type(args),
                "sftp_pass": args.sftp_password,
                "sftp_private_key": private_key_text(args.sftp_private_key_file),
                "sftp_key_passphrase": args.sftp_key_passphrase,
                "sftp_path": args.sftp_path,
                "publish_slug": args.publish_slug,
            }
        )
        if payload["sftp_auth_type"] == "password":
            payload["sftp_pass"] = payload["sftp_pass"] or getpass.getpass("SFTP password: ")
    else:
        payload.update(
            {
                "s3_endpoint": require(args.s3_endpoint, "--s3-endpoint"),
                "s3_bucket": require(args.s3_bucket, "--s3-bucket"),
                "s3_access_key": require(args.s3_access_key, "--s3-access-key or S3_ACCESS_KEY"),
                "s3_secret_key": require(args.s3_secret_key, "--s3-secret-key or S3_SECRET_KEY"),
            }
        )

    return payload


def nginx_server_block(web_root: str, server_name: str) -> str:
    return f"""# Managed by AutoGeo site_builder_publish.py
server {{
    listen 80;
    server_name {server_name};

    root {web_root};
    index index.html;

{DEFAULT_MIME_TYPES}
    default_type application/octet-stream;

    location / {{
        try_files $uri $uri/ =404;
    }}

    location ~* \\.html$ {{
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }}
}}
"""


def configure_nginx(cfg: NginxConfig) -> None:
    try:
        import paramiko
    except ImportError as exc:
        raise SystemExit("paramiko is required for --configure-nginx. Install backend dependencies first.") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_args: dict[str, Any] = {
        "hostname": cfg.host,
        "port": cfg.port,
        "username": cfg.username,
        "timeout": 30,
    }
    if cfg.private_key_path:
        connect_args["key_filename"] = cfg.private_key_path
        connect_args["passphrase"] = cfg.key_passphrase
    else:
        connect_args["password"] = cfg.password or getpass.getpass("SSH password for Nginx setup: ")

    print(f"[nginx] Connecting to {cfg.host}:{cfg.port} ...")
    client.connect(**connect_args)
    try:
        run_ssh(client, f"mkdir -p {shell_quote(cfg.web_root)}")
        run_ssh(client, f"mkdir -p {shell_quote(posixpath.dirname(cfg.conf_path))}")

        conf_text = nginx_server_block(cfg.web_root, cfg.server_name)
        sftp = client.open_sftp()
        try:
            tmp_path = f"/tmp/autogeo-nginx-{os.getpid()}.conf"
            with sftp.open(tmp_path, "w") as fh:
                fh.write(conf_text)
            run_ssh(client, f"mv {shell_quote(tmp_path)} {shell_quote(cfg.conf_path)}")
        finally:
            sftp.close()

        run_ssh(client, cfg.reload_command)
        print(f"[nginx] Configured {cfg.conf_path} for {cfg.server_name} -> {cfg.web_root}")
    finally:
        client.close()


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_ssh(client: Any, command: str) -> None:
    stdin, stdout, stderr = client.exec_command(command)
    del stdin
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if exit_code != 0:
        raise SystemExit(f"Remote command failed ({exit_code}): {command}\n{err or out}")


def post_json(url: str, token: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Deploy API failed: HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Deploy API is unreachable: {exc}") from exc


def main() -> int:
    args = apply_config(parse_args())
    if args.configure_nginx and args.method != "sftp":
        raise SystemExit("--configure-nginx is only useful with --method sftp")

    if args.configure_nginx:
        cfg = NginxConfig(
            host=require(args.sftp_host, "--sftp-host"),
            port=args.sftp_port,
            username=require(args.sftp_user, "--sftp-user"),
            password=args.sftp_password,
            private_key_path=args.sftp_private_key_file,
            key_passphrase=args.sftp_key_passphrase,
            web_root=args.sftp_path,
            server_name=args.server_name or host_from_url(args.public_base_url),
            conf_path=args.nginx_conf_path,
            reload_command=args.nginx_reload_command,
        )
        configure_nginx(cfg)

    payload = build_deploy_payload(args)
    api_base = args.api_base.rstrip("/")
    print(f"[deploy] Publishing site {args.site_id} via {args.method} ...")
    result = post_json(f"{api_base}/sites/deploy", args.token, payload)
    data = result.get("data", result)

    print("[deploy] Done")
    print(f"URL: {data.get('url')}")
    if data.get("target_path"):
        print(f"Target: {data.get('target_path')}")
    if data.get("warning"):
        print(f"Warning: {data.get('warning')}")
    if data.get("suggestion"):
        print(f"Suggestion: {data.get('suggestion')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
