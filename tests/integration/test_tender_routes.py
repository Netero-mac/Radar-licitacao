from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import create_app
from tests.integration.factories import PEDRA_PRETA, RONDONOPOLIS, make_tender


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(db_session: Session) -> dict[str, int]:
    ti = make_tender(
        db_session,
        municipality=RONDONOPOLIS,
        object_description="Manutenção de computadores & impressoras <urgente>",
        estimated_value=Decimal("5260541.6"),
        published_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        proposals_open_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        proposals_close_at=datetime(2099, 12, 1, 13, 0, tzinfo=UTC),
        raw_data={
            "processo": "39",
            "linkSistemaOrigem": "https://compras.exemplo.gov.br/39",
            "informacaoComplementar": "Inclui troca de peças.",
        },
    )
    food = make_tender(
        db_session,
        municipality=PEDRA_PRETA,
        object_description="Aquisição de gêneros alimentícios",
        modality_code=8,
        modality_name="Dispensa",
        estimated_value=None,
    )
    db_session.commit()
    return {"ti": ti.id, "food": food.id}


# --- API JSON ---------------------------------------------------------------------------


def test_api_lista_com_filtros(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get("/api/tenders", params={"q": "manutencao", "open_only": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["pages"] == 1
    item = body["items"][0]
    assert item["id"] == seeded["ti"]
    assert item["estimated_value"] == "5260541.6000"  # decimal como texto, sem perder precisão
    assert item["proposals_open"] is True
    assert item["municipality_name"] == "Rondonópolis"
    assert item["published_at"].startswith("2026-11-20T12:00:00")


def test_api_rejeita_filtro_invalido(client: TestClient, seeded: dict[str, int]) -> None:
    assert client.get("/api/tenders", params={"municipality": "abc"}).status_code == 422
    assert client.get("/api/tenders", params={"page_size": 500}).status_code == 422
    assert client.get("/api/tenders", params={"min_value": 10, "max_value": 1}).status_code == 422


def test_api_detalhe(client: TestClient, seeded: dict[str, int]) -> None:
    body = client.get(f"/api/tenders/{seeded['ti']}").json()

    assert body["agency"]["sphere"] == "municipal"
    assert body["process_number"] == "39"
    assert body["origin_system_url"] == "https://compras.exemplo.gov.br/39"
    assert "raw_data" not in body
    assert client.get("/api/tenders/999999").status_code == 404


def test_api_municipios_e_modalidades(client: TestClient, seeded: dict[str, int]) -> None:
    municipalities = client.get("/api/municipalities").json()
    modalities = client.get("/api/modalities").json()

    assert municipalities == [
        {"ibge_code": PEDRA_PRETA[0], "name": "Pedra Preta"},
        {"ibge_code": RONDONOPOLIS[0], "name": "Rondonópolis"},
    ]
    assert {"code": 6, "name": "Pregão - Eletrônico"} in modalities


def test_api_documentada_no_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/tenders" in paths
    params = {p["name"] for p in paths["/api/tenders"]["get"]["parameters"]}
    assert {"q", "municipality", "modality", "min_value", "max_value", "open_only"} <= params
    assert "/" not in paths  # telas HTML ficam fora da documentação da API


# --- Telas HTML -------------------------------------------------------------------------


def test_pagina_inicial_lista_licitacoes(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<html" in html
    assert "2 licitações encontradas" in html
    assert "R$ 5.260.541,60" in html
    # 13:00 UTC = 10:00 em Brasília (fuso padrão de exibição)
    assert "Propostas até 01/12/2099 10:00 (horário de Brasília)" in html
    assert "Rondonópolis/MT" in html
    assert f'href="/licitacoes/{seeded["ti"]}"' in html
    assert '<option value="5107602">Rondonópolis</option>' in html
    # Texto vindo do PNCP é escapado
    assert "&lt;urgente&gt;" in html and "<urgente>" not in html


def test_requisicao_htmx_recebe_so_os_resultados(
    client: TestClient, seeded: dict[str, int]
) -> None:
    response = client.get(
        "/", params={"q": "alimenticios"}, headers={"HX-Request": "true", "HX-Target": "results"}
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert "1 licitação encontrada" in response.text
    assert "Aquisição de gêneros alimentícios" in response.text
    assert response.headers["vary"] == "HX-Request, HX-Target"

    restore = client.get(
        "/",
        headers={
            "HX-Request": "true",
            "HX-Target": "results",
            "HX-History-Restore-Request": "true",
        },
    )
    assert "<html" in restore.text
    # Troca de UF mira #content: precisa da página inteira (o HTMX recorta com hx-select)
    whole = client.get("/", headers={"HX-Request": "true", "HX-Target": "content"})
    assert 'id="content"' in whole.text


def test_tela_ignora_filtro_invalido_com_aviso(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get("/", params={"municipality": "xyz", "q": "manutenção"})

    assert response.status_code == 200
    assert "Município:" in response.text
    assert "filtro ignorado" in response.text
    assert "1 licitação encontrada" in response.text


def test_tela_sem_resultados(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get("/", params={"q": "helicóptero"})

    assert "Nenhuma licitação encontrada com esses filtros" in response.text


def test_paginacao_preserva_filtros(client: TestClient, db_session: Session) -> None:
    for _ in range(21):
        make_tender(db_session, object_description="Manutenção de veículos")
    db_session.commit()

    html = client.get("/", params={"q": "veiculo"}).text

    assert "Página 1 de 2" in html
    assert 'href="/?q=veiculo&amp;page=2"' in html


def test_pagina_de_detalhe(client: TestClient, seeded: dict[str, int]) -> None:
    html = client.get(f"/licitacoes/{seeded['ti']}").text

    assert "Ver edital no PNCP" in html
    assert "https://pncp.gov.br/app/editais/" in html
    assert "https://compras.exemplo.gov.br/39" in html
    assert "Inclui troca de peças." in html
    assert "Aberto" in html


def test_detalhe_inexistente_retorna_404(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get("/licitacoes/999999")

    assert response.status_code == 404
    assert "Licitação não encontrada" in response.text


def test_arquivos_estaticos(client: TestClient) -> None:
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/vendor/htmx.min.js").status_code == 200


def test_com_uma_uf_nao_mostra_seletor_de_uf(client: TestClient, seeded: dict[str, int]) -> None:
    html = client.get("/").text

    assert "Licitações em Mato Grosso" in html
    assert 'name="state"' not in html
    assert '<option value="5107602">Rondonópolis</option>' in html


def test_com_varias_ufs_municipios_aparecem_depois_da_uf(
    client: TestClient, db_session: Session, seeded: dict[str, int]
) -> None:
    sp = make_tender(db_session, municipality=("3550308", "São Paulo"), state="SP")
    db_session.commit()

    html = client.get("/").text
    assert "Licitações públicas" in html
    assert '<option value="SP">SP · São Paulo</option>' in html
    assert "Escolha a UF primeiro" in html

    html = client.get("/", params={"state": "SP"}).text
    assert '<option value="SP" selected>' in html
    assert '<option value="3550308">São Paulo</option>' in html
    assert "Rondonópolis" not in html
    assert "1 licitação encontrada" in html
    assert f"/licitacoes/{sp.id}" in html


def test_municipio_de_outra_uf_e_descartado_na_tela(
    client: TestClient, db_session: Session, seeded: dict[str, int]
) -> None:
    make_tender(db_session, municipality=("3550308", "São Paulo"), state="SP")
    db_session.commit()

    # Rondonópolis (MT) ficou na URL depois de trocar a UF para SP
    html = client.get("/", params={"state": "SP", "municipality": RONDONOPOLIS[0]}).text

    assert "1 licitação encontrada" in html


def test_api_filtra_por_uf(client: TestClient, db_session: Session, seeded: dict[str, int]) -> None:
    make_tender(db_session, municipality=("3550308", "São Paulo"), state="SP")
    db_session.commit()

    assert client.get("/api/tenders", params={"state": "sp"}).json()["total"] == 1
    assert client.get("/api/tenders", params={"state": "MT"}).json()["total"] == 2
    assert client.get("/api/tenders", params={"state": "XX"}).status_code == 422
    assert client.get("/api/states").json() == [
        {"code": "MT", "name": "Mato Grosso"},
        {"code": "SP", "name": "São Paulo"},
    ]
    assert client.get("/api/municipalities", params={"state": "sp"}).json() == [
        {"ibge_code": "3550308", "name": "São Paulo"}
    ]


def test_valor_zero_aparece_como_sigiloso(client: TestClient, db_session: Session) -> None:
    tender = make_tender(
        db_session, object_description="Aquisição de medicamentos", estimated_value=Decimal("0")
    )
    db_session.commit()

    listing = client.get("/").text
    detail = client.get(f"/licitacoes/{tender.id}").text

    for html in (listing, detail):
        assert "Sigiloso" in html
        assert "R$ 0,00" not in html
