# AutoGeo Backend Dockerfile

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 使用阿里云 Debian 镜像源加速 apt（自动识别基础镜像 Debian 版本，避免硬编码 codename 导致 apt 源失效）
RUN . /etc/os-release && \
    echo "deb http://mirrors.aliyun.com/debian ${VERSION_CODENAME} main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian ${VERSION_CODENAME}-updates main" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security ${VERSION_CODENAME}-security main" >> /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libxshmfence1 \
    libatspi2.0-0 \
    fonts-wqy-microhei \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 可选的 Playwright 浏览器下载镜像（国内服务器可传 PLAYWRIGHT_DOWNLOAD_HOST 指定 npmmirror 等镜像加速）
ARG PLAYWRIGHT_DOWNLOAD_HOST
ENV PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST:-}

# Keep Python dependencies cacheable. This layer only changes when
# requirements.txt changes.
# pip 使用清华镜像源,避免国内服务器装依赖超时
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

RUN playwright install chromium

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH="/app"

# 使用阿里云 Debian 镜像源加速 apt（自动识别基础镜像 Debian 版本，避免硬编码 codename 导致 apt 源失效）
RUN . /etc/os-release && \
    echo "deb http://mirrors.aliyun.com/debian ${VERSION_CODENAME} main" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian ${VERSION_CODENAME}-updates main" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security ${VERSION_CODENAME}-security main" >> /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libxshmfence1 \
    libatspi2.0-0 \
    fonts-wqy-microhei \
    fonts-freefont-ttf \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    x11-utils \
    fluxbox \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Pre-inject noVNC CSS to hide control bar (done as root to avoid permission issues)
RUN if [ -f /usr/share/novnc/vnc.html ]; then \
      sed -i 's|</head>|<style id="autogeo-auth-hide-controls">#noVNC_control_bar_anchor,#noVNC_control_bar,#noVNC_control_bar_handle,#noVNC_side_dropdown,#noVNC_settings,#noVNC_clipboard,#noVNC_fullscreen_button,#noVNC_disconnect_button,#noVNC_logo,#noVNC_dot{display:none!important}#noVNC_container{cursor:default!important}</style></head>|' /usr/share/novnc/vnc.html; \
    fi

RUN useradd -m -u 1000 -s /bin/bash autogeo && \
    mkdir -p /app/data /app/logs /app/database /app/.cookies /app/backend/static && \
    chown -R autogeo:autogeo /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /ms-playwright /ms-playwright
ENV PATH="/opt/venv/bin:$PATH"

RUN mkdir -p /app/backend
COPY --chown=autogeo:autogeo . /app/backend/

COPY --chown=autogeo:autogeo entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && \
    sed -i 's/\r$//' /app/entrypoint.sh && \
    sed -i '1s/^\xEF\xBB\xBF//' /app/entrypoint.sh

# Put volatile metadata after expensive layers so BUILD_DATE/VCS_REF do not
# invalidate apt, pip, or Playwright caches.
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=3.3.1

LABEL maintainer="AutoGeo Team" \
      org.opencontainers.image.title="AutoGeo Backend" \
      org.opencontainers.image.description="FastAPI backend with Playwright" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONPATH="/app"
WORKDIR /app

ENV ENVIRONMENT=production \
    HOST=0.0.0.0 \
    PORT=8001 \
    PYTHONUNBUFFERED=1 \
    RAGFLOW_BASE_URL="" \
    DATABASE_URL="" \
    AUTO_GEO_ENCRYPTION_KEY=""

USER autogeo

EXPOSE 8001 6080

HEALTHCHECK --interval=15s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8001/api/health || exit 1

CMD ["/app/entrypoint.sh"]
