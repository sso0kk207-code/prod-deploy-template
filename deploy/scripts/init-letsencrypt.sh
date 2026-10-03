#!/usr/bin/env bash
# Первый выпуск сертификата Let's Encrypt. Нужно: DNS домена уже указывает на сервер, порты 80/443 открыты.
# Проблема «курица и яйцо»: nginx не стартует без сертификата, а сертификат выдаётся через nginx.
# Решение: временный самоподписанный сертификат -> старт nginx -> настоящий сертификат -> перезагрузка nginx.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

echo "==> временный сертификат для $DOMAIN"
$COMPOSE run --rm --entrypoint sh certbot -c "mkdir -p $CERT_DIR && openssl req -x509 -nodes -newkey rsa:2048 -days 1 -keyout $CERT_DIR/privkey.pem -out $CERT_DIR/fullchain.pem -subj '/CN=localhost'"

echo "==> старт nginx"
$COMPOSE up -d nginx

echo "==> запрос настоящего сертификата"
$COMPOSE run --rm --entrypoint sh certbot -c "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
$COMPOSE run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --email "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email

echo "==> перезагрузка nginx"
$COMPOSE exec nginx nginx -s reload
echo "OK: https://$DOMAIN"
