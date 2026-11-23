"""Configuração da aplicação, lida de variáveis de ambiente (e do arquivo .env)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Todas as modalidades publicadas no PNCP (ver app/collectors/pncp/modalities.py).
DEFAULT_MODALITIES = list(range(1, 14))


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

    # --- Coletor do PNCP ---
    pncp_base_url: str = "https://pncp.gov.br/api/consulta"
    pncp_timeout_seconds: float = Field(default=30.0, gt=0)
    pncp_max_retries: int = Field(default=5, ge=0)
    pncp_backoff_base_seconds: float = Field(default=2.0, ge=0)
    pncp_backoff_max_seconds: float = Field(default=60.0, ge=0)
    # A API aceita de 10 a 50 registros por página.
    pncp_page_size: int = Field(default=50, ge=10, le=50)
    pncp_state: str = Field(default="MT", min_length=2, max_length=2)
    pncp_modalities: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_MODALITIES)
    )
    # As datas da API vêm sem fuso; o PNCP usa o horário de Brasília.
    pncp_timezone: str = "America/Sao_Paulo"
    collection_lookback_days: int = Field(default=2, ge=1)

    @field_validator("pncp_modalities", mode="before")
    @classmethod
    def _parse_modalities(cls, value: object) -> object:
        """Aceita lista separada por vírgula no .env: PNCP_MODALITIES=6,8,9."""
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value

    @field_validator("pncp_state")
    @classmethod
    def _upper_state(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
