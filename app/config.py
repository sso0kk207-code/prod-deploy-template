from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT = "change-me"


class Settings(BaseSettings):
    """Вся конфигурация - из переменных окружения (12-factor). В .env.example перечислено всё, что можно задать."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"  # development | production
    secret_key: str = INSECURE_DEFAULT
    database_url: str = "sqlite:///./app.db"
    redis_url: str | None = None
    log_level: str = "INFO"
    cache_ttl: int = 60

    @model_validator(mode="after")
    def refuse_insecure_production(self):
        # Лучше упасть при старте, чем тихо работать в проде с известным всем секретом
        if self.env == "production" and (self.secret_key == INSECURE_DEFAULT or len(self.secret_key) < 32):
            raise ValueError("SECRET_KEY must be set to a random string of at least 32 characters in production")
        return self


def get_settings() -> Settings:
    return Settings()
