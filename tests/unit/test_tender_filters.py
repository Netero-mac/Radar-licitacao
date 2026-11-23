from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.schemas.tenders import TenderFilters, TenderPage
from app.services.tenders import _raw_extras, build_query, proposals_open

CUIABA = ZoneInfo("America/Cuiaba")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)


def test_campos_vazios_do_formulario_viram_sem_filtro() -> None:
    filters = TenderFilters.model_validate(
        {"q": "  ", "municipality": "", "modality": "", "min_value": "", "page": ""}
    )

    assert filters == TenderFilters()
    assert not filters.is_filtered


def test_converte_valores_do_formulario() -> None:
    filters = TenderFilters.model_validate(
        {
            "q": " manutenção ",
            "municipality": "5107602",
            "modality": "6",
            "min_value": "1000.50",
            "published_from": "2026-11-01",
            "open_only": "on",
            "page": "2",
        }
    )

    assert filters.q == "manutenção"
    assert filters.modality == 6
    assert filters.min_value == Decimal("1000.50")
    assert filters.published_from == date(2026, 11, 1)
    assert filters.open_only is True
    assert filters.page == 2


@pytest.mark.parametrize(
    "data",
    [
        {"min_value": "500", "max_value": "100"},
        {"published_from": "2026-11-20", "published_to": "2026-11-01"},
        {"municipality": "Rondonópolis"},
        {"page_size": "1000"},
        {"min_value": "-1"},
        {"state": "XX"},
    ],
)
def test_filtros_invalidos_geram_erro_na_validacao_estrita(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        TenderFilters.model_validate(data)


def test_modo_tolerante_ignora_filtro_invalido_e_explica() -> None:
    filters, errors = TenderFilters.from_query_lenient(
        {"q": "computador", "municipality": "abc", "min_value": "x"}
    )

    assert filters.q == "computador"
    assert filters.municipality is None
    assert filters.min_value is None
    assert len(errors) == 2
    assert any(error.startswith("Município:") for error in errors)


def test_modo_tolerante_descarta_faixa_invertida() -> None:
    filters, errors = TenderFilters.from_query_lenient({"min_value": "500", "max_value": "100"})

    assert (filters.min_value, filters.max_value) == (Decimal("500"), None)
    assert errors == ["Filtro: o valor mínimo não pode ser maior que o máximo"]


def test_parametros_de_url_omitem_padroes() -> None:
    filters = TenderFilters(q="pneu", open_only=True, page=3)

    assert filters.query_params() == {"q": "pneu", "open_only": "on", "page": "3"}
    assert filters.query_params(page=1) == {"q": "pneu", "open_only": "on"}
    assert TenderFilters().query_params() == {}


def test_total_de_paginas() -> None:
    assert TenderPage(items=[], total=0, page=1, page_size=20).pages == 1
    assert TenderPage(items=[], total=41, page=1, page_size=20).pages == 3


def test_datas_do_filtro_sao_dias_no_fuso_de_cuiaba() -> None:
    filters = TenderFilters(published_from=date(2026, 11, 22), published_to=date(2026, 11, 22))

    query = build_query(filters, CUIABA, NOW)

    assert query.published_since == datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
    assert query.published_before == datetime(2026, 11, 23, 4, 0, tzinfo=UTC)
    assert query.open_at is None


def test_filtro_de_propostas_abertas_usa_o_instante_atual() -> None:
    assert build_query(TenderFilters(open_only=True), CUIABA, NOW).open_at == NOW


@pytest.mark.parametrize(
    ("open_at", "close_at", "expected"),
    [
        (datetime(2026, 11, 20, tzinfo=UTC), datetime(2026, 11, 30, tzinfo=UTC), True),
        (datetime(2026, 11, 25, tzinfo=UTC), datetime(2026, 11, 30, tzinfo=UTC), True),
        (None, datetime(2026, 11, 22, 15, 0, tzinfo=UTC), False),
        (None, None, False),
    ],
)
def test_prazo_de_propostas(
    open_at: datetime | None, close_at: datetime | None, expected: bool
) -> None:
    tender = SimpleNamespace(proposals_open_at=open_at, proposals_close_at=close_at)

    assert proposals_open(tender, NOW) is expected  # type: ignore[arg-type]


def test_extras_do_registro_original() -> None:
    raw = {
        "processo": " 39 ",
        "amparoLegal": {"nome": "Lei 14.133/2021, Art. 28, I"},
        "modoDisputaNome": "Aberto",
        "informacaoComplementar": "Objeto X",
        "linkSistemaOrigem": "javascript:alert(1)",
    }

    extras = _raw_extras(raw, "Objeto X")

    assert extras["process_number"] == "39"
    assert extras["legal_basis"] == "Lei 14.133/2021, Art. 28, I"
    assert extras["dispute_mode"] == "Aberto"
    assert extras["complementary_info"] is None  # igual ao objeto: não repete
    assert extras["origin_system_url"] is None  # só http(s)

    assert (
        _raw_extras({"linkSistemaOrigem": "https://compras.mt.gov.br/x"}, "")["origin_system_url"]
        == "https://compras.mt.gov.br/x"
    )
    assert _raw_extras({}, "")["legal_basis"] is None


def test_uf_aceita_minusculas_e_tem_mensagem_em_portugues() -> None:
    assert TenderFilters.model_validate({"state": "mt"}).state == "MT"

    filters, errors = TenderFilters.from_query_lenient({"state": "zz"})
    assert filters.state is None
    assert errors == ["UF: UF desconhecida"]
