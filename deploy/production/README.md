# AutoGeo production deployment

This deployment runs AutoGeo as production containers:

- `autogeo_backend`: FastAPI backend on container port `8001` (host bind: `127.0.0.1:8001`)
- `autogeo_frontend`: Nginx static frontend on host port `8086`
- `autogeo_postgres`: PostgreSQL 15 database (data in volume `autogeo_postgres_data`)
- noVNC remote authorization desktop on host port `6080` (bind: `127.0.0.1:6080`)

## Server steps

```bash
cd /opt
git clone https://github.com/Ayfwq/Auto_GEO-main.git autogeo
cd /opt/autogeo
git checkout master
git pull origin master

cd deploy/production
cp .env.example .env
nano .env
./deploy.sh
```

Required values in `.env`:

- `POSTGRES_PASSWORD` / `DATABASE_URL`
- `AUTO_GEO_ENCRYPTION_KEY`
- `JWT_SECRET_KEY`
- `DEEPSEEK_API_KEY`
- `RAGFLOW_API_KEY`（后端启动强制校验，暂时不用 RAGFlow 也需填非空占位符）
- `CORS_ORIGINS`（改为你的域名/服务器 IP）
- 可选：`VOLCENGINE_ARK_*`（GEO 收录测评）、`FEISHU_*`（飞书机器人）、`ADSPOWER_*`（指纹浏览器）

Generate secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## BaoTa reverse proxy

Create a BaoTa site for your domain or server IP, then reverse proxy it to:

```text
http://127.0.0.1:8086
```

The frontend container proxies `/api` and `/ws` to the backend container.

Remote authorization desktop (noVNC) is exposed at `127.0.0.1:6080`. To access it
through the domain, add an extra reverse proxy:

```text
http://127.0.0.1:6080
```

and enable WebSocket support in BaoTa proxy settings.

## Useful commands

```bash
cd /opt/autogeo/deploy/production
docker compose --env-file .env -f docker-compose.yml ps
docker compose --env-file .env -f docker-compose.yml logs -f
docker compose --env-file .env -f docker-compose.yml restart
docker compose --env-file .env -f docker-compose.yml down
```

## Daily update

```bash
cd /opt/autogeo
cd deploy/production
./update.sh
```

`update.sh` pulls the latest code and chooses the smallest safe action:

- backend source changes: restart `backend`, because `../../backend` is mounted into the container
- backend dependency or Dockerfile changes: rebuild `backend`
- frontend changes: rebuild `frontend`, because production frontend is served as static files by nginx
- compose changes: rebuild/reconcile the stack

Run `./deploy.sh` for first-time deployment or when you want a full rebuild.
