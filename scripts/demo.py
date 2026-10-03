"""Демо: python scripts/demo.py http://127.0.0.1:8000  (локальный запуск; в проде те же ручки стоят за nginx)"""
from _demo import client, section, show

section("1. Liveness: процесс жив. Проба не ходит в БД, иначе оркестратор перезапускал бы здоровое приложение при сбое базы")
show("GET", "/health")

section("2. Readiness: можно ли слать трафик (БД и Redis доступны). Для недоступной зависимости вернётся 503")
show("GET", "/ready")

section("3. Работа API и сквозной X-Request-ID (nginx передаёт свой, приложение возвращает его в ответе и пишет в JSON-лог)")
show("POST", "/items", json_body={"name": "Mechanical keyboard", "price_cents": 8900}, headers={"X-Request-ID": "demo-trace-001"}, max_lines=8)
r = client.get("/items/1", headers={"X-Request-ID": "demo-trace-001"})
print("$ curl -H 'X-Request-ID: demo-trace-001' /items/1")
print(f"HTTP {r.status_code}   X-Request-ID: {r.headers['x-request-id']}   (тот же идентификатор вернулся клиенту)")
print()
r = client.get("/items/999")
print("$ curl /items/999")
print(f"HTTP {r.status_code}   X-Request-ID: {r.headers['x-request-id']}   (идентификатор создан автоматически)")
print()

section("4. Формат лога приложения: одна JSON-строка на запрос, готова для Loki / ELK")
print('{"ts": "2025-01-01T12:00:00+0000", "level": "INFO", "logger": "access", "msg": "request",')
print(' "request_id": "demo-trace-001", "method": "GET", "path": "/items/1", "status": 200, "ms": 3.2}')
print("# пример формата; реальные строки пишутся в stdout контейнера, docker ротирует их (10 МБ × 5 файлов)")
