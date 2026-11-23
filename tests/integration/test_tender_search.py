from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Tender
from app.schemas.tenders import TenderFilters
from app.services import tenders as service
from tests.integration.factories import CUIABA, PEDRA_PRETA, RONDONOPOLIS, make_tender

TZ = ZoneInfo("America/Cuiaba")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)


def _ids(session: Session, **filters: object) -> list[int]:
    page = service.search(session, TenderFilters.model_validate(filters), TZ, now=NOW)
    return [item.id for item in page.items]


def test_lista_as_mais_recentes_primeiro(db_session: Session) -> None:
    old = make_tender(db_session, published_at=datetime(2026, 11, 1, tzinfo=UTC))
    new = make_tender(db_session, published_at=datetime(2026, 11, 20, tzinfo=UTC))
    middle = make_tender(db_session, published_at=datetime(2026, 11, 10, tzinfo=UTC))

    assert _ids(db_session) == [new.id, middle.id, old.id]


def test_paginacao_e_total(db_session: Session) -> None:
    created = [
        make_tender(db_session, published_at=datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=i))
        for i in range(5)
    ]
    newest_first = [t.id for t in reversed(created)]

    page = service.search(db_session, TenderFilters(page=2, page_size=2), TZ, now=NOW)

    assert page.total == 5
    assert page.pages == 3
    assert [item.id for item in page.items] == newest_first[2:4]
    assert service.search(db_session, TenderFilters(page=9, page_size=2), TZ).items == []


def test_busca_textual_ignora_acentos_e_flexoes(db_session: Session) -> None:
    ti = make_tender(
        db_session, object_description="Contratação de MANUTENÇÃO preventiva de computadores"
    )
    make_tender(db_session, object_description="Aquisição de gêneros alimentícios")

    assert _ids(db_session, q="manutencao") == [ti.id]
    assert _ids(db_session, q="Manutenção computador") == [ti.id]  # todas as palavras, plural
    assert _ids(db_session, q="pavimentação") == []


def test_busca_aceita_frase_exata_ou_e_exclusao(db_session: Session) -> None:
    ar = make_tender(db_session, object_description="Manutenção de ar condicionado")
    pc = make_tender(db_session, object_description="Manutenção de computadores e impressoras")

    assert _ids(db_session, q='"ar condicionado"') == [ar.id]
    assert sorted(_ids(db_session, q="condicionado or impressora")) == sorted([ar.id, pc.id])
    assert _ids(db_session, q="manutenção -impressora") == [ar.id]


def test_busca_so_com_palavras_vazias_nao_filtra(db_session: Session) -> None:
    make_tender(db_session)

    assert len(_ids(db_session, q="de para")) == 1


def test_filtra_por_municipio_e_modalidade(db_session: Session) -> None:
    roo = make_tender(db_session, municipality=RONDONOPOLIS)
    pp = make_tender(
        db_session, municipality=PEDRA_PRETA, modality_code=8, modality_name="Dispensa"
    )
    make_tender(db_session, municipality=CUIABA)

    assert _ids(db_session, municipality=RONDONOPOLIS[0]) == [roo.id]
    assert _ids(db_session, modality=8) == [pp.id]
    assert _ids(db_session, municipality=PEDRA_PRETA[0], modality=6) == []


def test_filtra_por_faixa_de_valor(db_session: Session) -> None:
    cheap = make_tender(db_session, estimated_value=Decimal("999.99"))
    mid = make_tender(db_session, estimated_value=Decimal("50000"))
    make_tender(db_session, estimated_value=Decimal("2000000"))
    make_tender(db_session, estimated_value=None)  # sem valor: fica fora quando há faixa

    assert sorted(_ids(db_session, max_value="50000")) == sorted([cheap.id, mid.id])
    assert _ids(db_session, min_value="1000", max_value="50000") == [mid.id]
    assert len(_ids(db_session)) == 4


def test_periodo_usa_o_dia_no_horario_de_cuiaba(db_session: Session) -> None:
    # 22/11 às 23:30 em Cuiabá = 23/11 03:30 UTC
    late = make_tender(db_session, published_at=datetime(2026, 11, 23, 3, 30, tzinfo=UTC))
    # 23/11 às 00:30 em Cuiabá
    next_day = make_tender(db_session, published_at=datetime(2026, 11, 23, 4, 30, tzinfo=UTC))

    assert _ids(db_session, published_from="2026-11-22", published_to="2026-11-22") == [late.id]
    assert _ids(db_session, published_from=date(2026, 11, 23)) == [next_day.id]


def test_somente_propostas_abertas(db_session: Session) -> None:
    open_now = make_tender(
        db_session,
        proposals_open_at=NOW - timedelta(days=3),
        proposals_close_at=NOW + timedelta(days=5),
    )
    opens_later = make_tender(
        db_session,
        proposals_open_at=NOW + timedelta(days=1),
        proposals_close_at=NOW + timedelta(days=10),
    )
    make_tender(db_session, proposals_close_at=NOW - timedelta(minutes=1))
    make_tender(db_session, proposals_close_at=None)

    assert sorted(_ids(db_session, open_only=True)) == sorted([open_now.id, opens_later.id])

    page = service.search(db_session, TenderFilters(), TZ, now=NOW)
    flags = {item.id: item.proposals_open for item in page.items}
    assert flags[open_now.id] is True
    assert sum(flags.values()) == 2


def test_detalhe_e_lista_de_municipios(db_session: Session) -> None:
    tender: Tender = make_tender(
        db_session, municipality=PEDRA_PRETA, raw_data={"processo": "12/2026"}
    )
    make_tender(db_session, municipality=RONDONOPOLIS)
    make_tender(db_session, municipality=RONDONOPOLIS)

    detail = service.get_detail(db_session, tender.id)

    assert detail is not None
    assert detail.agency.cnpj == tender.agency.cnpj
    assert detail.process_number == "12/2026"
    assert service.get_detail(db_session, 999_999) is None
    assert service.municipalities(db_session) == [PEDRA_PRETA, RONDONOPOLIS]


def test_filtra_por_uf(db_session: Session) -> None:
    mt = make_tender(db_session)
    sp = make_tender(db_session, municipality=("3550308", "São Paulo"), state="SP")

    assert _ids(db_session, state="sp") == [sp.id]
    assert _ids(db_session, state="MT") == [mt.id]
    assert service.states(db_session) == ["MT", "SP"]
    assert service.municipalities(db_session, "SP") == [("3550308", "São Paulo")]


def test_busca_acha_o_plural_que_o_stemmer_nao_junta(db_session: Session) -> None:
    obras = make_tender(db_session, object_description="Execução de OBRAS de drenagem")
    pneus = make_tender(db_session, object_description="Aquisição de pneus")
    db_session.commit()

    assert _ids(db_session, q="obra") == [obras.id]
    assert _ids(db_session, q="pneu") == [pneus.id]
    assert _ids(db_session, q="obra -drenagem") == []
