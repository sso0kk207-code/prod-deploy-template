import json
import logging

import pytest

from app import main
from app.config import Settings
from tests.conftest import FakeRedis


def test_liveness_never_touches_dependencies(client, monkeypatch):
    monkeypatch.setattr(main, "check_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert client.get("/health").json() == {"status": "ok"}  # проба живости не должна зависеть от БД


def test_readiness_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "redis": "disabled"}


def test_readiness_returns_503_when_database_is_down(client, monkeypatch):
    def broken():
        raise ConnectionError("no route to host")

    monkeypatch.setattr(main, "check_db", broken)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["status"] == "unavailable" and r.json()["checks"]["database"] == "error: ConnectionError"


def test_readiness_reports_redis_state(client, monkeypatch):
    monkeypatch.setattr(main, "redis_client", FakeRedis())
    assert client.get("/ready").json()["checks"]["redis"] == "ok"
    monkeypatch.setattr(main, "redis_client", FakeRedis(fail=True))
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["redis"] == "error: ConnectionError"


def test_items_crud(client):
    r = client.post("/items", json={"name": "Keyboard", "price_cents": 8900})
    assert r.status_code == 201
    assert client.get(f"/items/{r.json()['id']}").json()["name"] == "Keyboard"
    assert len(client.get("/items").json()) == 1
    assert client.get("/items/999").status_code == 404
    assert client.post("/items", json={"name": "", "price_cents": 1}).status_code == 422
    assert client.post("/items", json={"name": "x", "price_cents": 0}).status_code == 422


def test_item_is_cached_in_redis(client, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(main, "redis_client", fake)
    iid = client.post("/items", json={"name": "Mouse", "price_cents": 2500}).json()["id"]
    client.get(f"/items/{iid}")
    assert f"item:{iid}" in fake.store
    assert client.get(f"/items/{iid}").json()["name"] == "Mouse"


def test_broken_cache_does_not_break_requests(client, monkeypatch):
    iid = client.post("/items", json={"name": "Mouse", "price_cents": 2500}).json()["id"]
    monkeypatch.setattr(main, "redis_client", FakeRedis(fail=True))
    assert client.get(f"/items/{iid}").status_code == 200  # без кэша работает, просто медленнее


def test_request_id_is_generated_and_propagated(client):
    assert len(client.get("/items").headers["x-request-id"]) >= 8
    assert client.get("/items", headers={"X-Request-ID": "trace-abc"}).headers["x-request-id"] == "trace-abc"


def test_access_log_is_json_with_request_id(client):
    from app.logs import JsonFormatter

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(JsonFormatter().format(record))

    h = Capture()
    logging.getLogger("access").addHandler(h)
    try:
        client.get("/items/12345", headers={"X-Request-ID": "trace-1"})
        client.get("/health")
    finally:
        logging.getLogger("access").removeHandler(h)
    line = json.loads(records[0])
    assert line["request_id"] == "trace-1" and line["path"] == "/items/12345" and line["status"] == 404 and line["level"] == "INFO"
    assert len(records) == 1  # /health в логи не попадает


def test_settings_refuse_insecure_secret_in_production():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(env="production", secret_key="change-me")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(env="production", secret_key="too-short")
    assert Settings(env="production", secret_key="x" * 40).env == "production"
    assert Settings(env="development").secret_key == "change-me"  # локально допустимо


def test_gunicorn_config_is_sane(monkeypatch):
    import importlib.util
    from pathlib import Path

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    spec = importlib.util.spec_from_file_location("gconf", Path(__file__).parent.parent / "gunicorn.conf.py")
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)
    assert 1 <= conf.workers <= 4 and conf.worker_class == "uvicorn_worker.UvicornWorker"
    assert conf.graceful_timeout < conf.timeout  # корректное завершение укладывается в таймаут
