"""Configuração da aplicação, lida de variáveis de ambiente (e do arquivo .env)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Obrigatória: sem valor padrão para não haver credenciais no código.
    database_url: str
    sql_echo: bool = False

    display_timezone: str = "America/Cuiaba"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
