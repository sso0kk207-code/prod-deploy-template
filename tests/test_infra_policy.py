"""Требования к инфраструктуре как тесты: если кто-то уберёт healthcheck, откроет порт БД или поставит :latest, CI упадёт."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
PROD = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
SERVICES = PROD["services"]
LONG_RUNNING = [n for n, s in SERVICES.items() if "profiles" not in s]


# ---------- docker-compose.prod.yml ----------
@pytest.mark.parametrize("name", LONG_RUNNING)
def test_services_restart_automatically(name):
    assert SERVICES[name]["restart"] == "unless-stopped"


def test_only_nginx_publishes_ports():
    published = {n: s["ports"] for n, s in SERVICES.items() if "ports" in s}
    assert list(published) == ["nginx"] and set(published["nginx"]) == {"80:80", "443:443"}


@pytest.mark.parametrize("name", ["nginx", "db", "redis", "certbot"])
def test_third_party_images_are_pinned(name):
    image = SERVICES[name]["image"]
    assert ":" in image and not image.endswith(":latest"), f"{name}: образ {image} без конкретной версии"


def test_api_container_is_hardened():
    api = SERVICES["api"]
    assert api["read_only"] is True and api["cap_drop"] == ["ALL"] and "no-new-privileges:true" in api["security_opt"]
    assert "healthcheck" in api and api["deploy"]["resources"]["limits"]["memory"]


def test_api_waits_for_healthy_database_and_stops_gracefully():
    assert SERVICES["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert int(SERVICES["api"]["stop_grace_period"].rstrip("s")) > 25  # больше graceful_timeout gunicorn
    assert "healthcheck" in SERVICES["db"]


def test_database_and_redis_are_not_on_the_edge_network():
    assert SERVICES["db"]["networks"] == ["internal"] and SERVICES["redis"]["networks"] == ["internal"] and SERVICES["api"]["networks"] == ["internal"]


def test_log_rotation_configured():
    for name in ("nginx", "api", "db", "redis"):
        assert SERVICES[name]["logging"]["options"]["max-size"], name


def test_redis_is_a_bounded_cache():
    cmd = " ".join(SERVICES["redis"]["command"])
    assert "--maxmemory " in cmd and "allkeys-lru" in cmd


def test_required_variables_fail_fast():
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for var in ("DOMAIN", "POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_DB"):
        assert f"${{{var}:?" in text, f"{var} должна быть обязательной"


def test_migrations_are_a_separate_step():
    assert SERVICES["migrate"]["command"] == "alembic upgrade head" and SERVICES["migrate"]["restart"] == "no"


# ---------- nginx ----------
NGINX = (ROOT / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
SITE = (ROOT / "deploy/nginx/templates/app.conf.template").read_text(encoding="utf-8")


def test_nginx_global_hardening():
    assert "server_tokens off;" in NGINX and "limit_req_zone" in NGINX and "log_format json" in NGINX


def test_site_uses_modern_tls_only():
    protocols = re.search(r"ssl_protocols ([^;]+);", SITE).group(1).split()
    assert set(protocols) == {"TLSv1.2", "TLSv1.3"}


def test_http_redirects_to_https_but_keeps_acme_challenge():
    assert "return 301 https://$host$request_uri;" in SITE and "/.well-known/acme-challenge/" in SITE


@pytest.mark.parametrize("header", ["Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"])
def test_security_headers_present(header):
    assert f'add_header {header}' in SITE


def test_proxy_forwards_client_info_and_request_id():
    for h in ("X-Real-IP", "X-Forwarded-For", "X-Forwarded-Proto", "X-Request-ID"):
        assert f"proxy_set_header {h}" in SITE
    assert "limit_req zone=api" in SITE


def test_readiness_endpoint_is_not_public():
    assert re.search(r"location = /ready \{[^}]*deny all;", SITE)


# ---------- Dockerfile ----------
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_dockerfile_is_multistage_non_root_with_healthcheck():
    assert DOCKERFILE.count("FROM ") == 2 and "AS builder" in DOCKERFILE
    assert re.search(r"^USER appuser", DOCKERFILE, re.M) and "HEALTHCHECK" in DOCKERFILE
    assert ":latest" not in DOCKERFILE and "gunicorn" in DOCKERFILE


def test_dockerignore_keeps_secrets_and_junk_out_of_the_image():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".env", ".git", "tests"} <= set(ignored)


# ---------- скрипты ----------
SCRIPTS = sorted((ROOT / "deploy/scripts").glob("*.sh"))


def test_expected_scripts_exist():
    assert {s.name for s in SCRIPTS} == {"deploy.sh", "backup.sh", "restore.sh", "server-setup.sh", "init-letsencrypt.sh"}


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda s: s.name)
def test_script_fails_fast(script):
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text


def _working_bash() -> str | None:
    """На Windows `bash` может оказаться заглушкой WSL без дистрибутива, поэтому пробуем Git Bash и проверяем, что оболочка реально запускается."""
    for candidate in (r"C:\Program Files\Gitinash.exe", shutil.which("bash")):
        if candidate and Path(candidate).exists():
            try:
                if subprocess.run([candidate, "-c", "exit 0"], capture_output=True, timeout=15).returncode == 0:
                    return candidate
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


BASH = _working_bash()


@pytest.mark.skipif(BASH is None, reason="рабочий bash не найден")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda s: s.name)
def test_script_syntax_is_valid(script):
    result = subprocess.run([BASH, "-n", script.as_posix()], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_deploy_script_rolls_back_and_backs_up_first():
    text = (ROOT / "deploy/scripts/deploy.sh").read_text(encoding="utf-8")
    assert text.index("backup.sh") < text.index("run --rm migrate") < text.index("up -d")  # бэкап -> миграции -> запуск
    assert "PREVIOUS_TAG" in text and "healthy" in text


def test_backup_script_rejects_empty_dumps_and_rotates():
    text = (ROOT / "deploy/scripts/backup.sh").read_text(encoding="utf-8")
    assert "-s " in text and "-mtime" in text and "pg_dump" in text


# ---------- CI/CD и секреты ----------
def test_workflows_are_valid_and_deploy_waits_for_tests():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    deploy = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    assert "test" in ci["jobs"]
    assert deploy[True]["workflow_run"]["workflows"] == ["CI"]  # YAML читает ключ `on` как True
    assert "success" in deploy["jobs"]["build-and-push"]["if"] and deploy["jobs"]["deploy"]["needs"] == "build-and-push"


def test_env_example_contains_no_real_secrets():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith(("POSTGRES_PASSWORD=", "SECRET_KEY=")):
            assert line.split("=", 1)[1].split("#")[0].strip() == "", line


def test_env_file_is_gitignored():
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
