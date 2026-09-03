#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/.env"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

has_changes() {
  local pattern
  for pattern in "$@"; do
    if grep -Eq "$pattern" "$CHANGED_FILES"; then
      return 0
    fi
  done
  return 1
}

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  echo "Copy .env.example to .env and fill the required secrets first."
  exit 1
fi

cd "$REPO_DIR"

BEFORE_REF="$(git rev-parse HEAD)"
git pull --ff-only
AFTER_REF="$(git rev-parse HEAD)"

if [ "$BEFORE_REF" = "$AFTER_REF" ]; then
  echo "Already up to date."
  compose ps
  exit 0
fi

CHANGED_FILES="$(mktemp)"
trap 'rm -f "$CHANGED_FILES"' EXIT
git diff --name-only "$BEFORE_REF" "$AFTER_REF" > "$CHANGED_FILES"

if has_changes '^deploy/production/docker-compose\.yml$' '^deploy/production/\.env\.example$'; then
  echo "Compose deployment files changed; rebuilding and reconciling services..."
  export BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  export VCS_REF="$AFTER_REF"
  compose up -d --build
else
  export BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  export VCS_REF="$AFTER_REF"

  if has_changes '^backend/(Dockerfile|requirements\.txt|entrypoint\.sh)$'; then
    echo "Backend image inputs changed; rebuilding backend..."
    compose up -d --build backend
  elif has_changes '^backend/'; then
    echo "Backend source changed; rebuilding backend image (no volume mount in production)..."
    compose up -d --build backend
  fi

  if has_changes '^frontend/'; then
    echo "Frontend changed; rebuilding static frontend..."
    compose up -d --build frontend
  fi
fi

compose ps

echo
echo "Update complete."
