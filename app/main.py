import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine, get_db
from app.logs import install_request_logging, setup_logging
from app.models import Item

settings = get_settings()
setup_logging(settings.log_level)

redis_client = None
if settings.redis_url:
    import redis

    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.env != "production":
        Base.metadata.create_all(engine)  # в проде схему ведёт отдельный шаг миграций (alembic upgrade head)
    yield


app = FastAPI(
    title="Production-ready API",
    version="1.0.0",
    description=f"Шаблон сервиса для продакшена: пробы живости и готовности, JSON-логи, конфигурация из окружения. Окружение: **{settings.env}**.",
    lifespan=lifespan,
)
install_request_logging(app)


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_cents: int = Field(gt=0)


def check_db() -> str:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return "ok"


def check_redis() -> str:
    if redis_client is None:
        return "disabled"
    redis_client.ping()
    return "ok"


@app.get("/health", tags=["probes"], summary="Liveness: процесс жив (без обращения к зависимостям)")
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["probes"], summary="Readiness: зависимости доступны, можно слать трафик")
def ready():
    checks, ok = {}, True
    for name, fn in (("database", check_db), ("redis", check_redis)):
        try:
            checks[name] = fn()
        except Exception as exc:  # noqa: BLE001 - причина недоступности попадает в ответ пробы
            checks[name], ok = f"error: {type(exc).__name__}", False
    return JSONResponse({"status": "ready" if ok else "unavailable", "checks": checks, "env": settings.env}, status_code=200 if ok else 503)


@app.post("/items", status_code=201, tags=["items"])
def create_item(data: ItemIn, db: Session = Depends(get_db)):
    item = Item(**data.model_dump())
    db.add(item)
    db.commit()
    return {"id": item.id, "name": item.name, "price_cents": item.price_cents}


@app.get("/items", tags=["items"])
def list_items(db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "price_cents": i.price_cents} for i in db.scalars(select(Item).order_by(Item.id).limit(100))]


@app.get("/items/{item_id}", tags=["items"])
def get_item(item_id: int, db: Session = Depends(get_db)):
    key = f"item:{item_id}"
    if redis_client is not None:
        try:
            if hit := redis_client.get(key):
                return json.loads(hit)
        except Exception:  # noqa: BLE001 - недоступный кэш не должен ронять запрос
            pass
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    data = {"id": item.id, "name": item.name, "price_cents": item.price_cents}
    if redis_client is not None:
        try:
            redis_client.set(key, json.dumps(data), ex=settings.cache_ttl)
        except Exception:  # noqa: BLE001
            pass
    return data
