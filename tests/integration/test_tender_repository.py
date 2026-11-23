import copy
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.pncp import PncpPage
from app.models import Agency, Sphere, Tender
from app.repositories.tenders import upsert_agencies
from app.services.collection import store_page
from tests.conftest import load_fixture

BRASILIA = ZoneInfo("America/Sao_Paulo")
ITEMS = load_fixture("publicacao_mt_pregao_eletronico_p1.json")["data"]


def _page(items: list[dict]) -> PncpPage:
    return PncpPage(
        number=1, total_pages=1, total_records=len(items), remaining_pages=0, items=items
    )


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_insere_contratacoes_novas(db_session: Session) -> None:
    result = store_page(db_session, _page(ITEMS), BRASILIA)
    db_session.commit()

    assert (result.new, result.updated) == (50, 0)
    assert _count(db_session, Tender) == 50
    assert _count(db_session, Agency) == len({i["orgaoEntidade"]["cnpj"] for i in ITEMS})


def test_reprocessar_a_mesma_pagina_nao_duplica_nem_atualiza(db_session: Session) -> None:
    store_page(db_session, _page(ITEMS), BRASILIA)
    db_session.commit()
    updated_at_before = db_session.scalar(select(func.max(Tender.updated_at)))

    result = store_page(db_session, _page(copy.deepcopy(ITEMS)), BRASILIA)
    db_session.commit()

    assert (result.new, result.updated) == (0, 0)
    assert _count(db_session, Tender) == 50
    assert db_session.scalar(select(func.max(Tender.updated_at))) == updated_at_before


def test_atualiza_somente_o_que_mudou(db_session: Session) -> None:
    store_page(db_session, _page(ITEMS[:3]), BRASILIA)
    db_session.commit()
    changed = copy.deepcopy(ITEMS[:3])
    changed[0]["situacaoCompraId"] = 3
    changed[0]["situacaoCompraNome"] = "Anulada"
    changed[0]["valorTotalEstimado"] = 1234.56

    result = store_page(db_session, _page([*changed, ITEMS[3]]), BRASILIA)
    db_session.commit()

    assert (result.new, result.updated) == (1, 1)
    tender = db_session.scalars(
        select(Tender).where(Tender.pncp_control_number == ITEMS[0]["numeroControlePNCP"])
    ).one()
    db_session.refresh(tender)
    assert tender.status == "Anulada"
    assert tender.status_code == 3
    assert str(tender.estimated_value) == "1234.5600"
    assert tender.raw_data["situacaoCompraNome"] == "Anulada"
    assert tender.updated_at > tender.created_at


def test_registro_repetido_na_mesma_pagina_e_gravado_uma_vez(db_session: Session) -> None:
    result = store_page(db_session, _page([ITEMS[0], ITEMS[1], ITEMS[0]]), BRASILIA)
    db_session.commit()

    assert result.new == 2
    assert _count(db_session, Tender) == 2


def test_registro_malformado_e_ignorado(db_session: Session) -> None:
    broken = {**ITEMS[1], "unidadeOrgao": None}

    result = store_page(db_session, _page([ITEMS[0], broken]), BRASILIA)
    db_session.commit()

    assert result.new == 1


def test_busca_textual_funciona_nos_dados_gravados(db_session: Session) -> None:
    store_page(db_session, _page(ITEMS), BRASILIA)
    db_session.commit()

    query = select(func.count()).where(
        Tender.search_vector.op("@@")(func.plainto_tsquery("pt_unaccent", "expediente"))
    )
    assert (db_session.scalar(query) or 0) >= 1


def test_upsert_de_orgao_atualiza_nome(db_session: Session) -> None:
    ids = upsert_agencies(
        db_session, [{"cnpj": "03347135000116", "name": "Antigo", "sphere": Sphere.MUNICIPAL}]
    )
    again = upsert_agencies(
        db_session, [{"cnpj": "03347135000116", "name": "Novo", "sphere": Sphere.MUNICIPAL}]
    )
    db_session.commit()

    assert ids == again
    assert db_session.scalars(select(Agency.name)).one() == "Novo"
    assert upsert_agencies(db_session, []) == {}


def test_orgao_sem_esfera_de_governo_e_gravado(db_session: Session) -> None:
    raw = copy.deepcopy(ITEMS[0])
    raw["orgaoEntidade"]["esferaId"] = "N"

    result = store_page(db_session, _page([raw]), BRASILIA)
    db_session.commit()

    assert result.new == 1
    assert db_session.scalars(select(Agency.sphere)).one() == Sphere.NOT_APPLICABLE
