"""Gunicorn с воркерами Uvicorn: управление процессами (перезапуск упавших воркеров, graceful reload) плюс скорость ASGI."""
import multiprocessing
import os

bind = "0.0.0.0:8000"
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 4)))
timeout = 30                 # зависший воркер перезапускается
graceful_timeout = 25        # при SIGTERM воркеры успевают дообработать текущие запросы (меньше stop_grace_period в compose)
keepalive = 5                # соединения от nginx переиспользуются
max_requests = 2000          # плановая перезагрузка воркера против утечек памяти
max_requests_jitter = 200
accesslog = None             # access-лог пишет приложение в JSON (app/logs.py)
errorlog = "-"
forwarded_allow_ips = "*"    # за nginx в закрытой docker-сети: доверяем X-Forwarded-*
