from collections.abc import Iterator
from datetime import date
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.pncp import PncpClient
from app.collectors.pncp.client import PUBLISHED_PATH
from app.models import CollectionRun, CollectionStatus, CollectionTrigger, Tender
from app.services.collection import run_collection
from tests.conftest import load_fixture

BASE_URL = "https://pncp.test/api/consulta"
BRASILIA = ZoneInfo("America/Sao_Paulo")
PAGE_1 = load_fixture("publicacao_mt_pregao_eletronico_p1.json")
PAGE_2 = load_fixture("publicacao_mt_pregao_eletronico_p2.json")


@pytest.fixture
def client() -> Iterator[PncpClient]:
    with PncpClient(BASE_URL, max_retries=2, sleep=lambda _: None) as pncp:
        yield pncp


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL) as router:
        yield router


def _mock_pregao(api: respx.MockRouter, page_2: httpx.Response | None = None) -> None:
    """Pregão eletrônico (6) com duas páginas reais; demais modalidades sem registros."""
    api.get(PUBLISHED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "1"}).mock(
        return_value=httpx.Response(200, json=PAGE_1)
    )
    api.get(PUBLISHED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "2"}).mock(
        return_value=page_2 or httpx.Response(200, json=PAGE_2)
    )
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))


def _run(session: Session, client: PncpClient) -> CollectionRun:
    return run_collection(
        session,
        client,
        date_from=date(2026, 11, 17),
        date_to=date(2026, 11, 18),
        state="MT",
        modalities=[4, 6, 8],
        source_tz=BRASILIA,
        trigger=CollectionTrigger.CLI,
    )


def _tender_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Tender)) or 0


def test_coleta_completa_registra_a_execucao(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    _mock_pregao(api)

    run = _run(db_session, client)

    assert run.status == CollectionStatus.SUCCESS
    assert run.pages_fetched == 2
    assert (run.tenders_new, run.tenders_updated) == (58, 0)
    assert run.finished_at is not None and run.finished_at >= run.started_at
    assert run.error_message is None
    assert _tender_count(db_session) == 58

    saved = db_session.get(CollectionRun, run.id)
    assert saved is not None and saved.status == CollectionStatus.SUCCESS


def test_segunda_coleta_do_mesmo_periodo_nao_duplica(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    _mock_pregao(api)

    _run(db_session, client)
    second = _run(db_session, client)

    assert (second.tenders_new, second.tenders_updated) == (0, 0)
    assert _tender_count(db_session) == 58
    assert db_session.scalar(select(func.count()).select_from(CollectionRun)) == 2


def test_erro_da_api_marca_execucao_como_falha_e_mantem_paginas_salvas(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    _mock_pregao(api, page_2=httpx.Response(500))

    run = _run(db_session, client)

    assert run.status == CollectionStatus.FAILED
    assert run.error_message is not None and "após 3 tentativas" in run.error_message
    assert run.pages_fetched == 1
    assert run.tenders_new == 50
    assert run.finished_at is not None
    assert _tender_count(db_session) == 50  # a página 1 ficou salva


def test_periodo_invertido_e_rejeitado(db_session: Session, client: PncpClient) -> None:
    with pytest.raises(ValueError, match="data inicial"):
        run_collection(
            db_session,
            client,
            date_from=date(2026, 11, 18),
            date_to=date(2026, 11, 17),
            state="MT",
            modalities=[6],
            source_tz=BRASILIA,
            trigger=CollectionTrigger.CLI,
        )
