#!/usr/bin/env bash
# Деплой новой версии на сервере: ./deploy/scripts/deploy.sh <тег-образа>
# Порядок: pull -> бэкап БД -> миграции -> запуск -> ожидание healthy -> при неудаче откат на предыдущий тег.
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG="${1:?usage: deploy.sh <image-tag>}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
PREVIOUS_TAG="$(grep -E '^TAG=' .env | cut -d= -f2 || true)"

wait_healthy() {
  local cid status
  for _ in $(seq 1 30); do
    cid="$($COMPOSE ps -q api)"
    status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)"
    [ "$status" = "healthy" ] && return 0
    sleep 2
  done
  return 1
}

echo "==> [1/5] pull образа $TAG"
TAG="$TAG" $COMPOSE pull api

echo "==> [2/5] бэкап базы перед миграциями"
./deploy/scripts/backup.sh

echo "==> [3/5] миграции"
TAG="$TAG" $COMPOSE --profile tools run --rm migrate

echo "==> [4/5] запуск версии $TAG"
TAG="$TAG" $COMPOSE up -d --remove-orphans api nginx db redis certbot

echo "==> [5/5] ожидание healthcheck"
if wait_healthy; then
  sed -i "s/^TAG=.*/TAG=$TAG/" .env
  docker image prune -f >/dev/null
  echo "OK: версия $TAG работает"
else
  echo "ОШИБКА: версия $TAG не стала healthy. Откат на ${PREVIOUS_TAG:-<нет предыдущей>}" >&2
  if [ -n "$PREVIOUS_TAG" ]; then
    TAG="$PREVIOUS_TAG" $COMPOSE up -d --no-deps api
  fi
  $COMPOSE logs --tail=50 api >&2 || true
  exit 1
fi
