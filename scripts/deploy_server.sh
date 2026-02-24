#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Support both layouts:
# 1) project/scripts/deploy_server.sh
# 2) project/deploy_server.sh
if [[ -f "$SCRIPT_DIR/docker-compose.server.yaml" ]]; then
  ROOT_DIR="$SCRIPT_DIR"
elif [[ -f "$SCRIPT_DIR/../docker-compose.server.yaml" ]]; then
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  ROOT_DIR="$SCRIPT_DIR"
fi

COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.server.yaml}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [command]

Commands:
  up       Pull latest images and start services in background (default)
  down     Stop and remove services
  restart  Restart all services
  pull     Pull latest images only
  status   Show service status
  logs     Follow logs (default service: api)
  config   Render resolved compose config

Environment overrides:
  COMPOSE_FILE  (default: $ROOT_DIR/docker-compose.server.yaml)
  ENV_FILE      (default: $ROOT_DIR/.env)
EOF
}

require_files() {
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Error: compose file not found: $COMPOSE_FILE" >&2
    exit 1
  fi

  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: env file not found: $ENV_FILE" >&2
    if [[ -f "$ROOT_DIR/.env.server.example" ]]; then
      echo "Hint: cp $ROOT_DIR/.env.server.example $ROOT_DIR/.env" >&2
    fi
    exit 1
  fi
}

require_docker_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker is not installed." >&2
    exit 1
  fi

  if ! docker compose version >/dev/null 2>&1; then
    echo "Error: docker compose is not available." >&2
    exit 1
  fi
}

dc() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

main() {
  local cmd="${1:-up}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  case "$cmd" in
    -h|--help|help)
      usage
      return
      ;;
  esac

  require_docker_compose
  require_files

  case "$cmd" in
    up)
      dc pull "$@"
      dc up -d "$@"
      dc ps
      ;;
    down)
      dc down "$@"
      ;;
    restart)
      dc down "$@"
      dc up -d "$@"
      dc ps
      ;;
    pull)
      dc pull "$@"
      ;;
    status|ps)
      dc ps "$@"
      ;;
    logs)
      if [[ $# -eq 0 ]]; then
        set -- api
      fi
      dc logs -f "$@"
      ;;
    config)
      dc config
      ;;
    *)
      echo "Error: unknown command '$cmd'" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
