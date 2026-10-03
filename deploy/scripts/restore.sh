#!/usr/bin/env bash
# Восстановление БД из бэкапа: ./deploy/scripts/restore.sh /var/backups/myapp/db-2025-01-01-0300.sql.gz
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

FILE="${1:?usage: restore.sh <backup.sql.gz>}"
[ -f "$FILE" ] || { echo "Файл не найден: $FILE" >&2; exit 1; }

read -r -p "ВСЕ текущие данные базы $POSTGRES_DB будут заменены данными из $FILE. Продолжить? [yes/N] " answer
[ "$answer" = "yes" ] || { echo "Отменено"; exit 1; }

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
$COMPOSE stop api
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" -c "CREATE DATABASE \"$POSTGRES_DB\";"
gunzip -c "$FILE" | $COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1
$COMPOSE up -d api
echo "OK: база восстановлена из $FILE"
