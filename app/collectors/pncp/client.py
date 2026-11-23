"""Cliente HTTP da API de consulta do PNCP.

- timeout em toda requisição;
- novas tentativas com backoff exponencial em 5xx, timeout e falha de rede;
- 429 (rate limit) também é repetido, respeitando o cabeçalho Retry-After;
- 204 significa "nenhum registro" (a API não manda corpo nesse caso);
- paginação percorrida até a última página.
"""

import logging
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import httpx

from app import __version__
from app.collectors.pncp.schemas import PncpPage
from app.config import Settings

logger = logging.getLogger(__name__)

PUBLISHED_PATH = "/v1/contratacoes/publicacao"
# Teto para um Retry-After absurdo não travar a coleta.
MAX_RETRY_AFTER_SECONDS = 600.0

_RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class PncpError(Exception):
    """Falha definitiva ao consultar o PNCP (sem mais tentativas)."""


def _format_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Lê Retry-After em segundos ou como data HTTP."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = (retry_at - datetime.now(UTC)).total_seconds()
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


class PncpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        backoff_max: float = 60.0,
        page_size: int = 50,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.page_size = page_size
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": f"radar-licitacoes-mt/{__version__}",
            },
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            settings.pncp_base_url,
            timeout=settings.pncp_timeout_seconds,
            max_retries=settings.pncp_max_retries,
            backoff_base=settings.pncp_backoff_base_seconds,
            backoff_max=settings.pncp_backoff_max_seconds,
            page_size=settings.pncp_page_size,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def iter_published(
        self, date_from: date, date_to: date, modality: int, state: str
    ) -> Iterator[PncpPage]:
        """Contratações publicadas no período (datas inclusivas), página a página."""
        params: dict[str, Any] = {
            "dataInicial": _format_date(date_from),
            "dataFinal": _format_date(date_to),
            "codigoModalidadeContratacao": modality,
            "uf": state,
        }
        return self._iter_pages(PUBLISHED_PATH, params)

    def _iter_pages(self, path: str, params: dict[str, Any]) -> Iterator[PncpPage]:
        page_number = 1
        while True:
            body = self._get_json(
                path, {**params, "pagina": page_number, "tamanhoPagina": self.page_size}
            )
            if body is None:  # 204: nada (mais) a retornar
                return
            page = self._parse_page(body, page_number)
            if not page.items:
                return
            yield page
            if page.remaining_pages <= 0 or page_number >= page.total_pages:
                return
            page_number += 1

    @staticmethod
    def _parse_page(body: Any, page_number: int) -> PncpPage:
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise PncpError(f"resposta inesperada do PNCP na página {page_number}")
        return PncpPage(
            number=int(body.get("numeroPagina", page_number)),
            total_pages=int(body.get("totalPaginas", 0)),
            total_records=int(body.get("totalRegistros", 0)),
            remaining_pages=int(body.get("paginasRestantes", 0)),
            items=body["data"],
        )

    def _backoff(self, attempt: int) -> float:
        return min(self.backoff_base * 2**attempt, self.backoff_max)

    def _get_json(self, path: str, params: dict[str, Any]) -> Any | None:
        """GET com novas tentativas. Retorna o JSON, ou None quando a API responde 204."""
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.get(path, params=params)
            except _RETRYABLE_ERRORS as exc:
                reason = f"{type(exc).__name__}: {exc}"
                delay = self._backoff(attempt)
            else:
                if response.status_code == httpx.codes.NO_CONTENT:
                    return None
                if response.is_success:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise PncpError(f"JSON inválido em {path}: {exc}") from exc
                if response.status_code != httpx.codes.TOO_MANY_REQUESTS and (
                    response.status_code < httpx.codes.INTERNAL_SERVER_ERROR
                ):
                    raise PncpError(
                        f"PNCP respondeu {response.status_code} em {path}: {response.text[:300]}"
                    )
                reason = f"HTTP {response.status_code}"
                retry_after = _retry_after_seconds(response)
                delay = self._backoff(attempt) if retry_after is None else retry_after

            if attempt == self.max_retries:
                raise PncpError(
                    f"PNCP indisponível em {path} após {attempt + 1} tentativas ({reason})"
                )
            logger.warning(
                "Falha ao consultar o PNCP, nova tentativa em %.1fs",
                delay,
                extra={
                    "path": path,
                    "page": params.get("pagina"),
                    "attempt": attempt + 1,
                    "reason": reason,
                },
            )
            self._sleep(delay)
        raise AssertionError("inalcançável")  # pragma: no cover
