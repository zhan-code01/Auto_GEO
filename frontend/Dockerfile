# AutoGeo Frontend Dockerfile

FROM node:22-alpine AS builder

WORKDIR /app

# Keep dependency installation cacheable. This layer only changes when package
# manifests change.
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com
RUN npm ci --include=dev

COPY . .

ARG VITE_API_BASE_URL
ARG VITE_WS_URL
ARG VITE_STATIC_URL
ARG VITE_ENABLE_MOCK
ARG VITE_APP_TITLE

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_WS_URL=${VITE_WS_URL}
ENV VITE_STATIC_URL=${VITE_STATIC_URL}
ENV VITE_ENABLE_MOCK=${VITE_ENABLE_MOCK:-false}
ENV VITE_APP_TITLE=${VITE_APP_TITLE:-AutoGeo}

RUN npm run build:renderer

FROM nginx:alpine

RUN apk update && apk upgrade && rm -rf /var/cache/apk/*

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/out/renderer /usr/share/nginx/html

RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid

# Put volatile metadata after expensive layers so BUILD_DATE/VCS_REF do not
# invalidate npm install or nginx setup caches.
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=3.3.1

LABEL maintainer="AutoGeo Team" \
      org.opencontainers.image.title="AutoGeo Frontend" \
      org.opencontainers.image.description="Vue 3 + Vite Frontend served by Nginx" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}"

USER nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
