import os

os.environ.update({"ENV": "development", "DATABASE_URL": "sqlite://", "REDIS_URL": ""})

import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, engine


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(main.app) as c:
        yield c


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.store, self.fail, self.gets = {}, fail, 0

    def _check(self):
        if self.fail:
            raise ConnectionError("redis down")

    def ping(self):
        self._check()
        return True

    def get(self, key):
        self._check()
        self.gets += 1
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self._check()
        self.store[key] = value
