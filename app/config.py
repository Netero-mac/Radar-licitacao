"""Configuração da aplicação, lida de variáveis de ambiente (e do arquivo .env)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.geo import STATES

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

    # Fuso das datas nas telas e e-mails. Editais e PNCP usam o horário de Brasília.
    display_timezone: str = "America/Sao_Paulo"

    # --- Coletor do PNCP ---
    pncp_base_url: str = "https://pncp.gov.br/api/consulta"
    pncp_timeout_seconds: float = Field(default=30.0, gt=0)
    pncp_max_retries: int = Field(default=5, ge=0)
    pncp_backoff_base_seconds: float = Field(default=2.0, ge=0)
    pncp_backoff_max_seconds: float = Field(default=60.0, ge=0)
    # A API aceita de 10 a 50 registros por página.
    pncp_page_size: int = Field(default=50, ge=10, le=50)
    # UFs coletadas. Lista vazia = Brasil inteiro (uma consulta só, sem filtro de UF).
    pncp_states: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["MT"])
    # Intervalo mínimo entre requisições, para não estourar o limite do PNCP (429).
    pncp_request_interval_seconds: float = Field(default=1.0, ge=0)
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

    @field_validator("pncp_states", mode="before")
    @classmethod
    def _parse_states(cls, value: object) -> object:
        """PNCP_STATES=MT,MS,GO; vazio (ou "BR") = todas as UFs."""
        if isinstance(value, str):
            value = [part for part in value.replace(" ", "").split(",") if part]
            if [part.upper() for part in value] == ["BR"]:
                return []
        return value

    @field_validator("pncp_states")
    @classmethod
    def _check_states(cls, value: list[str]) -> list[str]:
        states = list(dict.fromkeys(state.upper() for state in value))
        unknown = [state for state in states if state not in STATES]
        if unknown:
            raise ValueError(f"UF desconhecida: {', '.join(unknown)}")
        return states


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
