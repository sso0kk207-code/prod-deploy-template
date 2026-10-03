#!/usr/bin/env bash
# Ежедневный бэкап PostgreSQL: ./deploy/scripts/backup.sh   (cron: 0 3 * * * /opt/myapp/deploy/scripts/backup.sh)
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

BACKUP_DIR="${BACKUP_DIR:-/var/backups/myapp}"
KEEP_DAYS="${KEEP_DAYS:-14}"
FILE="$BACKUP_DIR/db-$(date +%F-%H%M).sql.gz"

mkdir -p "$BACKUP_DIR"
docker compose -f docker-compose.prod.yml --env-file .env exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILE"

# Пустой или подозрительно маленький файл = бэкапа нет: падаем громко, а не молча
if [ ! -s "$FILE" ] || [ "$(stat -c%s "$FILE")" -lt 200 ]; then
  echo "ОШИБКА: бэкап пустой: $FILE" >&2
  rm -f "$FILE"
  exit 1
fi

find "$BACKUP_DIR" -name 'db-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "OK: $FILE ($(du -h "$FILE" | cut -f1))"
