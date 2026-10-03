#!/usr/bin/env bash
# Первичная настройка чистого сервера Ubuntu 22.04/24.04 (от root): ./server-setup.sh deploy "ssh-ed25519 AAAA..."
set -euo pipefail

USER_NAME="${1:?usage: server-setup.sh <deploy-user> <ssh-public-key>}"
PUBKEY="${2:?укажите публичный SSH-ключ}"

apt-get update && apt-get -y upgrade
apt-get -y install ufw fail2ban unattended-upgrades curl git

# Docker из официального скрипта
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

# Отдельный пользователь для деплоя: вход только по ключу, без root
id "$USER_NAME" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$USER_NAME"
usermod -aG docker "$USER_NAME"
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
echo "$PUBKEY" > "/home/$USER_NAME/.ssh/authorized_keys"
chown "$USER_NAME:$USER_NAME" "/home/$USER_NAME/.ssh/authorized_keys" && chmod 600 "/home/$USER_NAME/.ssh/authorized_keys"

sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/; s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# Файрвол: наружу только SSH, HTTP и HTTPS
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable

systemctl enable --now fail2ban unattended-upgrades

install -d -o "$USER_NAME" -g "$USER_NAME" /opt/myapp /var/backups/myapp
echo "Готово. Дальше: клонировать репозиторий в /opt/myapp, создать .env, запустить deploy/scripts/init-letsencrypt.sh"
