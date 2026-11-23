from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.categories import CATEGORIES, Category
from app.db import get_session
from app.main import create_app
from app.repositories import dashboard as repository
from app.schemas.dashboard import DashboardFilters, RankingParams
from app.services import dashboard as service
from tests.integration.factories import CUIABA, PEDRA_PRETA, make_tender

BRASILIA = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)
FILTERS = DashboardFilters(months=3)  # set, out e nov de 2026


def _tender(session: Session, published: datetime, **overrides: object) -> None:
    make_tender(session, published_at=published, **overrides)


@pytest.fixture
def data(db_session: Session) -> None:
    nov = datetime(2026, 11, 10, 12, tzinfo=UTC)
    _tender(
        db_session,
        nov,
        object_description="Aquisição de computadores",
        estimated_value=Decimal("100000"),
        proposals_close_at=NOW + timedelta(days=3),
    )
    _tender(
        db_session,
        nov,
        object_description="Locação de pneus e combustível",
        estimated_value=Decimal("50000.50"),
    )
    _tender(
        db_session,
        nov,
        municipality=PEDRA_PRETA,
        object_description="Reforma da escola",
        estimated_value=None,
    )
    _tender(
        db_session,
        datetime(2026, 9, 5, 12, tzinfo=UTC),
        municipality=CUIABA,
        object_description="Manutenção de computadores e veículos",
        estimated_value=Decimal("2000000"),
    )
    # 1º/out 02:00 UTC = 30/set 23:00 em Brasília: conta em setembro
    _tender(
        db_session,
        datetime(2026, 10, 1, 2, tzinfo=UTC),
        municipality=CUIABA,
        object_description="Contratação de mão de obra terceirizada",
        estimated_value=Decimal("10"),
    )
    # fora do período (agosto) e de outra UF
    _tender(db_session, datetime(2026, 8, 31, 12, tzinfo=UTC), object_description="Computadores")
    _tender(
        db_session,
        nov,
        municipality=("5002704", "Campo Grande"),
        state="MS",
        object_description="Computadores",
        estimated_value=Decimal("1"),
    )
    db_session.commit()


def test_resumo(db_session: Session, data: None) -> None:
    summary = service.summary(db_session, FILTERS, BRASILIA, NOW)

    assert summary.tenders == 6  # agosto fica fora do período
    assert summary.total_value == Decimal("2150011.50")
    assert (summary.without_value, summary.open_now, summary.municipalities) == (1, 1, 4)

    mt = service.summary(db_session, FILTERS.model_copy(update={"state": "MT"}), BRASILIA, NOW)
    assert (mt.tenders, mt.municipalities) == (5, 3)


def test_ranking_de_municipios_por_quantidade_e_por_valor(db_session: Session, data: None) -> None:
    by_count = service.municipalities(db_session, FILTERS, RankingParams(limit=2), BRASILIA, NOW)
    by_value = service.municipalities(
        db_session, FILTERS, RankingParams(order="value", limit=10), BRASILIA, NOW
    )

    # empate em quantidade: desempata pelo valor
    assert [(i.label, i.tenders) for i in by_count.items] == [
        ("Cuiabá/MT", 2),
        ("Rondonópolis/MT", 2),
    ]
    assert by_count.total_municipalities == 4
    assert [i.label for i in by_value.items] == [
        "Cuiabá/MT",
        "Rondonópolis/MT",
        "Campo Grande/MS",
        "Pedra Preta/MT",  # sem valor: soma zero
    ]
    assert by_value.items[-1].total_value == 0


def test_categorias_com_sobreposicao_e_sem_categoria(db_session: Session, data: None) -> None:
    result = service.categories(db_session, FILTERS, BRASILIA, NOW)
    counts = {item.key: item.tenders for item in result.items}

    assert counts["ti"] == 3  # computadores (nov, set) e Campo Grande
    assert counts["veiculos"] == 2  # pneus/combustível e "computadores e veículos"
    assert counts["obras"] == 1  # reforma; "mão de obra" não é obra
    assert result.items[0].key == "ti"  # maior quantidade primeiro
    assert result.uncategorized.tenders == 1  # mão de obra terceirizada
    assert result.total_tenders == 6


def test_plurais_que_o_stemmer_nao_junta(db_session: Session) -> None:
    category = Category("x", "X", ("pneu", "pneus", "construção", "construções"))
    for text in ("Pneu aro 15", "Pneus aro 15", "Construção de ponte", "Construções diversas"):
        make_tender(db_session, object_description=text, published_at=NOW)
    db_session.commit()

    groups, rest = repository.by_category(db_session, [], [category])

    assert (groups[0].tenders, rest.tenders) == (4, 0)


def test_termos_das_categorias_sao_validos(db_session: Session) -> None:
    assert repository.ineffective_category_queries(db_session, CATEGORIES) == []
    assert repository.ineffective_category_queries(db_session, [Category("v", "V", ("de",))]) == [
        "v"
    ]


def test_evolucao_mensal_preenche_meses_vazios(db_session: Session, data: None) -> None:
    result = service.monthly(db_session, FILTERS, BRASILIA, NOW)

    assert [(i.label, i.tenders, i.partial) for i in result.items] == [
        ("set/26", 2, False),
        ("out/26", 0, False),
        ("nov/26", 4, True),
    ]
    assert result.items[0].total_value == Decimal("2000010")
    assert result.items[1].total_value == 0


# --- API e tela ------------------------------------------------------------------------


@pytest.fixture
def client(db_session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def recent(db_session: Session) -> None:
    """Licitações relativas a agora (a API usa a data atual)."""
    now = datetime.now(UTC)
    make_tender(
        db_session,
        object_description="Computadores",
        published_at=now,
        estimated_value=Decimal("1234.5"),
    )
    make_tender(
        db_session,
        municipality=CUIABA,
        object_description="Pneus",
        published_at=now - timedelta(days=1),
        estimated_value=None,
    )
    db_session.commit()


def test_endpoints_json(client: TestClient, recent: None) -> None:
    summary = client.get("/api/dashboard/summary", params={"months": 3}).json()
    assert (summary["tenders"], summary["total_value"], summary["without_value"]) == (
        2,
        "1234.5000",
        1,
    )
    assert summary["period"]["months"] == 3

    ranking = client.get("/api/dashboard/municipalities", params={"order": "value"}).json()
    assert [item["label"] for item in ranking["items"]] == ["Rondonópolis/MT", "Cuiabá/MT"]

    categories = client.get("/api/dashboard/categories").json()
    assert {item["key"]: item["tenders"] for item in categories["items"]}["ti"] == 1
    assert "pneus" in next(i for i in categories["items"] if i["key"] == "veiculos")["keywords"]

    monthly = client.get("/api/dashboard/monthly", params={"months": 6}).json()
    assert len(monthly["items"]) == 6
    assert monthly["items"][-1]["partial"] is True
    assert sum(item["tenders"] for item in monthly["items"]) == 2


@pytest.mark.parametrize(
    ("path", "params", "message"),
    [
        ("summary", {"months": "5"}, "escolha 3, 6, 12 ou 24 meses"),
        ("summary", {"state": "XX"}, "UF desconhecida"),
        ("municipalities", {"limit": "500"}, "menor ou igual a 50"),
        ("municipalities", {"order": "nome"}, "valor inválido"),
    ],
)
def test_parametros_invalidos_em_portugues(
    client: TestClient, path: str, params: dict[str, str], message: str
) -> None:
    response = client.get(f"/api/dashboard/{path}", params=params)

    assert response.status_code == 422
    assert message in response.json()["detail"][0]["msg"]


def test_tela_do_painel(client: TestClient, recent: None) -> None:
    html = client.get("/painel", params={"months": "6"}).text

    assert '<option value="6" selected>' in html
    assert "R$ 1.234,50" in html  # tabelas renderizadas no servidor
    assert "1 sem valor informado" in html
    assert "Rondonópolis/MT" in html
    assert "/api/dashboard/municipalities?months=6&amp;order=tenders" in html
    assert 'integrity="sha384-' in html  # Chart.js do CDN com verificação de integridade
    assert "(em andamento)" in html


def test_tela_sem_dados_e_filtro_invalido(client: TestClient) -> None:
    html = client.get("/painel", params={"months": "7"}).text

    assert "Período: escolha 3, 6, 12 ou 24 meses" in html
    assert "Nenhuma licitação publicada neste período" in html
    assert "data-chart " not in html
