import copy
from collections.abc import Iterator
from datetime import date
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.pncp import PncpClient
from app.collectors.pncp.client import PUBLISHED_PATH, UPDATED_PATH
from app.models import CollectionRun, CollectionStatus, CollectionTrigger, Tender
from app.services.collection import run_collection
from tests.conftest import load_fixture

BASE_URL = "https://pncp.test/api/consulta"
BRASILIA = ZoneInfo("America/Sao_Paulo")
PAGE_1 = load_fixture("publicacao_mt_pregao_eletronico_p1.json")
PAGE_2 = load_fixture("publicacao_mt_pregao_eletronico_p2.json")
# Resposta real de /atualizacao (MT, pregão, 16 a 21/11): 50 registros, dos quais 35
# publicados antes do período (1 revogada e 1 suspensa entre eles).
UPDATES = load_fixture("atualizacao_mt_pregao_eletronico_p1.json")


@pytest.fixture
def client() -> Iterator[PncpClient]:
    with PncpClient(BASE_URL, max_retries=2, sleep=lambda _: None) as pncp:
        yield pncp


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL) as router:
        yield router


def _mock_pregao(
    api: respx.MockRouter, page_2: httpx.Response | None = None, *, updates: bool = True
) -> None:
    """Pregão eletrônico (6) com duas páginas reais; demais modalidades sem registros.

    ``updates``: /atualizacao responde sem registros (False = rota não registrada).
    """
    api.get(PUBLISHED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "1"}).mock(
        return_value=httpx.Response(200, json=PAGE_1)
    )
    api.get(PUBLISHED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "2"}).mock(
        return_value=page_2 or httpx.Response(200, json=PAGE_2)
    )
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))
    if updates:
        api.get(UPDATED_PATH).mock(return_value=httpx.Response(204))


def _run(session: Session, client: PncpClient, **kwargs: object) -> CollectionRun:
    return run_collection(
        session,
        client,
        date_from=date(2026, 11, 17),
        date_to=date(2026, 11, 18),
        states=["MT"],
        modalities=[4, 6, 8],
        source_tz=BRASILIA,
        trigger=CollectionTrigger.CLI,
        **kwargs,  # type: ignore[arg-type]
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
    assert saved.states == ["MT"]


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
    _mock_pregao(api, page_2=httpx.Response(500), updates=False)  # para antes delas

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
            states=["MT"],
            modalities=[6],
            source_tz=BRASILIA,
            trigger=CollectionTrigger.CLI,
        )


def test_sem_ufs_coleta_o_brasil_inteiro_numa_consulta(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))
    updates = api.get(UPDATED_PATH).mock(return_value=httpx.Response(204))

    run = run_collection(
        db_session,
        client,
        date_from=date(2026, 11, 17),
        date_to=date(2026, 11, 18),
        states=[],
        modalities=[6, 8],
        source_tz=BRASILIA,
        trigger=CollectionTrigger.CLI,
    )

    assert run.status == CollectionStatus.SUCCESS
    assert run.states == []
    assert route.call_count == 2  # uma por modalidade, sem repetir por UF
    assert all("uf" not in call.request.url.params for call in route.calls)
    assert updates.call_count == 2


def test_varias_ufs_consultam_cada_uma(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))
    api.get(UPDATED_PATH).mock(return_value=httpx.Response(204))

    _ = run_collection(
        db_session,
        client,
        date_from=date(2026, 11, 17),
        date_to=date(2026, 11, 18),
        states=["MT", "MS"],
        modalities=[6],
        source_tz=BRASILIA,
        trigger=CollectionTrigger.CLI,
    )

    assert [call.request.url.params["uf"] for call in route.calls] == ["MT", "MS"]


def test_busca_tambem_as_alteracoes_do_periodo(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))
    updates = api.get(UPDATED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "1"})
    updates.mock(return_value=httpx.Response(200, json=UPDATES))
    api.get(UPDATED_PATH).mock(return_value=httpx.Response(204))

    run = _run(db_session, client)

    assert run.status == CollectionStatus.SUCCESS
    assert updates.call_count == 1
    params = updates.calls[0].request.url.params
    assert (params["dataInicial"], params["dataFinal"], params["uf"]) == (
        "20261117",
        "20261118",
        "MT",
    )
    assert run.tenders_new == 50
    # Licitações publicadas meses antes entram, com a situação atual.
    statuses = dict(
        db_session.execute(select(Tender.status_code, func.count()).group_by(Tender.status_code))
        .tuples()
        .all()
    )
    assert statuses == {1: 48, 2: 1, 4: 1}


def test_alteracao_atualiza_prazo_e_situacao_de_licitacao_conhecida(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    _mock_pregao(api)
    _run(db_session, client)

    changed = copy.deepcopy(PAGE_1["data"][0])
    changed |= {
        "dataEncerramentoProposta": "2026-12-20T09:00:00",
        "situacaoCompraId": 4,
        "situacaoCompraNome": "Suspensa",
        "dataAtualizacaoGlobal": "2026-11-21T10:00:00",
    }
    api.routes.clear()
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))
    api.get(UPDATED_PATH, params={"codigoModalidadeContratacao": "6", "pagina": "1"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [changed],
                "totalRegistros": 1,
                "totalPaginas": 1,
                "numeroPagina": 1,
                "paginasRestantes": 0,
                "empty": False,
            },
        )
    )
    api.get(UPDATED_PATH).mock(return_value=httpx.Response(204))

    run = _run(db_session, client)

    assert (run.tenders_new, run.tenders_updated) == (0, 1)
    tender = db_session.scalars(
        select(Tender).where(Tender.pncp_control_number == changed["numeroControlePNCP"])
    ).one()
    db_session.refresh(tender)
    assert (tender.status_code, tender.status) == (4, "Suspensa")
    assert tender.proposals_close_at is not None
    assert tender.proposals_close_at.isoformat() == "2026-12-20T12:00:00+00:00"


def test_sem_atualizacoes_so_consulta_as_publicacoes(
    db_session: Session, client: PncpClient, api: respx.MockRouter
) -> None:
    _mock_pregao(api, updates=False)  # chamar /atualizacao daria erro de rota não mockada

    run = _run(db_session, client, include_updates=False)

    assert run.status == CollectionStatus.SUCCESS
    assert run.tenders_new == 58
