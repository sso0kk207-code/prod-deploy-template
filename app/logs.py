"""Структурные JSON-логи с request-id: их читают Loki, ELK, CloudWatch; по request-id запрос находится сквозь nginx и приложение."""
import json
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
SKIP_PATHS = {"/health"}  # пробы оркестратора не засоряют логи


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname, "logger": record.name, "msg": record.getMessage(), "request_id": request_id_var.get()}
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def install_request_logging(app: FastAPI) -> None:
    log = logging.getLogger("access")

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]  # nginx передаёт свой id, иначе создаём
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            if request.url.path not in SKIP_PATHS:
                # логируем ДО сброса контекста, иначе в строке access-лога request_id будет «-»
                log.info("request", extra={"extra_fields": {"method": request.method, "path": request.url.path, "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1)}})
            return response
        except Exception:
            log.exception("unhandled error", extra={"extra_fields": {"path": request.url.path}})
            raise
        finally:
            request_id_var.reset(token)
