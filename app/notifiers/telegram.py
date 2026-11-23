"""Envio de mensagens pelo Telegram (Bot API, método sendMessage)."""

import logging
from collections.abc import Iterable

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Limite do Telegram por mensagem (em caracteres).
MAX_MESSAGE_LENGTH = 4096


class TelegramError(Exception):
    pass


def split_message(blocks: Iterable[str], limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Agrupa blocos (cabeçalho, uma licitação por bloco) em mensagens dentro do limite.

    Um bloco nunca é cortado no meio (quebraria as tags HTML); um bloco maior que o
    limite sozinho é truncado.
    """
    messages: list[str] = []
    current = ""
    for block in blocks:
        block = block if len(block) <= limit else block[: limit - 1] + "…"
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.telegram.org",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._http = httpx.Client(
            base_url=api_url.rstrip("/"), timeout=timeout, transport=transport
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "TelegramClient | None":
        """None quando não há TELEGRAM_BOT_TOKEN (envio pelo Telegram desativado)."""
        if not settings.telegram_bot_token:
            return None
        return cls(
            settings.telegram_bot_token.get_secret_value(), api_url=settings.telegram_api_url
        )

    def close(self) -> None:
        self._http.close()

    def _safe(self, text: str) -> str:
        """O token vai na URL: nunca deixá-lo aparecer em mensagens de erro e logs."""
        return text.replace(self._token, "***")

    def send_message(self, chat_id: str, text: str) -> None:
        try:
            response = self._http.post(
                f"/bot{self._token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
            )
        except httpx.HTTPError as exc:
            raise TelegramError(self._safe(f"falha de conexão com o Telegram: {exc}")) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != httpx.codes.OK or not body.get("ok"):
            description = body.get("description") or response.text[:200]
            raise TelegramError(
                self._safe(f"Telegram respondeu {response.status_code}: {description}")
            )
