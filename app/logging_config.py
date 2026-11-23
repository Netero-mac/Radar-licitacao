"""Logs estruturados usando apenas o módulo logging da biblioteca padrão.

Campos passados em ``extra={...}`` aparecem no log como chaves próprias.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

# Atributos padrão de LogRecord, que não devem ser repetidos como campos extras.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extra_fields(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = " ".join(f"{k}={v!r}" for k, v in _extra_fields(record).items())
        return f"{line} {extras}" if extras else line


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # O httpx registra cada URL em INFO; a do Telegram contém o token do bot. Os eventos
    # relevantes (páginas coletadas, falhas, novas tentativas) já são logados pela aplicação.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, root.level))
