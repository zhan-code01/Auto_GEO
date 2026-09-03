#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/.env"
EXPECTED_REF="775b32cb29abca519cb49e2452b0c910de901c8f"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command docker
require_command git

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  echo "Copy .env.example to .env and fill the required secrets first."
  exit 1
fi

cd "$REPO_DIR"
CURRENT_REF="$(git rev-parse HEAD)"
if ! git merge-base --is-ancestor "$EXPECTED_REF" "$CURRENT_REF"; then
  echo "Warning: current git ref is $CURRENT_REF, and it does not include AB96-0CBE."
  echo "Continuing with the current checked-out master."
fi

export BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export VCS_REF="$CURRENT_REF"

compose build
compose run --rm --no-deps frontend npm ci --include=dev
compose up -d
compose ps

echo
echo "AutoGeo is starting:"
echo "  Frontend: http://127.0.0.1:8086"
echo "  Health:   http://127.0.0.1:8086/api/health"
echo
echo "Daily update after code changes:"
echo "  cd $SCRIPT_DIR && ./update.sh"
echo
echo "Logs:"
echo "  cd $SCRIPT_DIR && docker compose --env-file .env -f docker-compose.yml logs -f"
