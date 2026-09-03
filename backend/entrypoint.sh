#!/usr/bin/env bash
set -euo pipefail

# ============================================
# AutoGeo Backend Entrypoint
# Starts Xvfb + x11vnc + noVNC before the backend.
# This lets users view the Playwright browser during QR-code authorization.
# ============================================

DISPLAY_NUMBER="${DISPLAY_NUMBER:-99}"
SCREEN_RESOLUTION="${SCREEN_RESOLUTION:-1280x800x24}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
VNC_PORT="${VNC_PORT:-5900}"
export DISPLAY=":${DISPLAY_NUMBER}"

echo "=========================================="
echo "AutoGeo backend starting"
echo "DISPLAY=${DISPLAY}"
echo "SCREEN_RESOLUTION=${SCREEN_RESOLUTION}"
echo "NOVNC_PORT=${NOVNC_PORT}"
echo "=========================================="

cleanup() {
  echo "Stopping background desktop services..."
  jobs -p | xargs -r kill || true
}
trap cleanup EXIT TERM INT

# Clean up stale lock files from previous crashes
rm -f /tmp/.X${DISPLAY_NUMBER}-lock /tmp/.X11-unix/X${DISPLAY_NUMBER} 2>/dev/null || true

echo "Starting Xvfb..."
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_RESOLUTION}" -ac +extension RANDR &

echo "Waiting for Xvfb..."
for i in $(seq 1 20); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    echo "Xvfb is ready on ${DISPLAY}"
    break
  fi

  if [ "$i" = "20" ]; then
    echo "Xvfb failed to start"
    exit 1
  fi

  sleep 0.5
done

if command -v fluxbox >/dev/null 2>&1; then
  echo "Configuring fluxbox to hide toolbar (single-window auth experience)..."
  mkdir -p "${HOME}/.fluxbox"
  cat > "${HOME}/.fluxbox/init" <<'FB'
session.screen0.toolbar.visible:	false
session.screen0.toolbar.onTop:	false
session.screen0.toolbar.autoHide:	true
session.screen0.toolbar.widthPercent:	100
session.screen0.toolbar.placement:	BottomCenter
FB
  echo "Starting fluxbox..."
  fluxbox >/tmp/fluxbox.log 2>&1 &
fi

echo "Starting x11vnc..."
if [ -n "${VNC_PASSWORD:-}" ]; then
  VNC_PASS_FILE="/tmp/autogeo-vnc-pass"
  x11vnc -storepasswd "${VNC_PASSWORD}" "${VNC_PASS_FILE}" >/dev/null 2>&1
  chmod 600 "${VNC_PASS_FILE}"
  x11vnc -display "${DISPLAY}" -forever -shared -rfbport "${VNC_PORT}" -rfbauth "${VNC_PASS_FILE}" >/tmp/x11vnc.log 2>&1 &
else
  echo "WARNING: VNC_PASSWORD is empty. noVNC desktop is not password protected."
  x11vnc -display "${DISPLAY}" -forever -shared -nopw -rfbport "${VNC_PORT}" >/tmp/x11vnc.log 2>&1 &
fi

sleep 1

echo "Starting noVNC websockify..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" >/tmp/novnc.log 2>&1 &

echo "=========================================="
echo "Remote desktop ready:"
echo "  http://<server-ip>:${NOVNC_PORT}/vnc.html"
echo "=========================================="

# ==================== Database Migration ====================
# PostgreSQL schema is managed through Alembic migrations.
RUN_DB_MIGRATIONS="${RUN_DB_MIGRATIONS:-true}"
DATABASE_URL="${DATABASE_URL:-}"

if ! echo "${DATABASE_URL}" | grep -qi "postgresql"; then
  echo "Only PostgreSQL DATABASE_URL values are supported"
  exit 1
fi

if [ "${RUN_DB_MIGRATIONS}" = "true" ]; then
  echo "PostgreSQL detected - running Alembic migrations..."
  cd /app/backend

  if command -v alembic >/dev/null 2>&1; then
    alembic upgrade head
    echo "alembic upgrade head OK"
  else
    echo "alembic not found; PostgreSQL schema migration cannot run"
    exit 1
  fi

  cd /app
fi

echo "Backend starting..."
echo "=========================================="

exec python -m backend.main
