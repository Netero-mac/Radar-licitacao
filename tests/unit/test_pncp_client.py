from collections.abc import Iterator
from datetime import date

import httpx
import pytest
import respx

from app.collectors.pncp import PncpClient, PncpError
from app.collectors.pncp.client import MAX_RETRY_AFTER_SECONDS, PUBLISHED_PATH
from tests.conftest import load_fixture

BASE_URL = "https://pncp.test/api/consulta"
PAGE_1 = load_fixture("publicacao_mt_pregao_eletronico_p1.json")
PAGE_2 = load_fixture("publicacao_mt_pregao_eletronico_p2.json")


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def client(sleeps: list[float]) -> Iterator[PncpClient]:
    with PncpClient(
        BASE_URL, max_retries=3, backoff_base=1.0, backoff_max=5.0, sleep=sleeps.append
    ) as pncp:
        yield pncp


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


def _collect(client: PncpClient) -> list[int]:
    pages = client.iter_published(date(2026, 11, 17), date(2026, 11, 18), 6, "MT")
    return [page.number for page in pages]


def test_envia_parametros_exigidos_pela_api(client: PncpClient, api: respx.MockRouter) -> None:
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))

    _collect(client)

    params = route.calls.last.request.url.params
    assert dict(params) == {
        "dataInicial": "20261117",
        "dataFinal": "20261118",
        "codigoModalidadeContratacao": "6",
        "uf": "MT",
        "pagina": "1",
        "tamanhoPagina": "50",
    }


def test_percorre_todas_as_paginas(client: PncpClient, api: respx.MockRouter) -> None:
    api.get(PUBLISHED_PATH, params={"pagina": "1"}).mock(
        return_value=httpx.Response(200, json=PAGE_1)
    )
    api.get(PUBLISHED_PATH, params={"pagina": "2"}).mock(
        return_value=httpx.Response(200, json=PAGE_2)
    )
    page_3 = api.get(PUBLISHED_PATH, params={"pagina": "3"}).mock(return_value=httpx.Response(204))

    pages = list(client.iter_published(date(2026, 11, 17), date(2026, 11, 18), 6, "MT"))

    assert [page.number for page in pages] == [1, 2]
    assert sum(len(page.items) for page in pages) == PAGE_1["totalRegistros"] == 58
    assert not page_3.called  # paginasRestantes = 0 na página 2: não pede a próxima


def test_204_significa_nenhum_registro(client: PncpClient, api: respx.MockRouter) -> None:
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))

    assert _collect(client) == []


def test_para_quando_a_pagina_vem_vazia(client: PncpClient, api: respx.MockRouter) -> None:
    empty = {**PAGE_1, "data": [], "paginasRestantes": 5}
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(200, json=empty))

    assert _collect(client) == []
    assert route.call_count == 1


def test_repete_em_erro_5xx_com_backoff_exponencial(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    single_page = {**PAGE_2, "numeroPagina": 1, "totalPaginas": 1}
    route = api.get(PUBLISHED_PATH).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(502),
            httpx.Response(503),
            httpx.Response(200, json=single_page),
        ]
    )

    assert _collect(client) == [1]
    assert route.call_count == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_backoff_respeita_o_limite_maximo(sleeps: list[float], api: respx.MockRouter) -> None:
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(500))
    client = PncpClient(
        BASE_URL, max_retries=4, backoff_base=2.0, backoff_max=5.0, sleep=sleeps.append
    )

    with pytest.raises(PncpError):
        _collect(client)

    assert sleeps == [2.0, 4.0, 5.0, 5.0]


def test_repete_em_timeout_e_falha_de_conexao(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    api.get(PUBLISHED_PATH).mock(
        side_effect=[
            httpx.ReadTimeout("demorou"),
            httpx.ConnectError("recusada"),
            httpx.Response(204),
        ]
    )

    assert _collect(client) == []
    assert sleeps == [1.0, 2.0]


def test_429_respeita_retry_after(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    api.get(PUBLISHED_PATH).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(429),  # sem Retry-After: usa o backoff normal
            httpx.Response(204),
        ]
    )

    _collect(client)

    assert sleeps == [7.0, 2.0]


def test_retry_after_em_formato_de_data_e_com_teto(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    api.get(PUBLISHED_PATH).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            httpx.Response(503, headers={"Retry-After": "99999"}),
            httpx.Response(429, headers={"Retry-After": "logo"}),
            httpx.Response(204),
        ]
    )

    _collect(client)

    # data no passado -> 0s; valor enorme -> teto; valor ilegível -> backoff (1 * 2^2)
    assert sleeps == [0.0, MAX_RETRY_AFTER_SECONDS, 4.0]


def test_desiste_apos_o_maximo_de_tentativas(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(500))

    with pytest.raises(PncpError, match="após 4 tentativas"):
        _collect(client)

    assert route.call_count == 4
    assert len(sleeps) == 3


def test_erro_4xx_nao_e_repetido(
    client: PncpClient, api: respx.MockRouter, sleeps: list[float]
) -> None:
    route = api.get(PUBLISHED_PATH).mock(
        return_value=httpx.Response(422, json={"message": "dataFinal inválida"})
    )

    with pytest.raises(PncpError, match="422"):
        _collect(client)

    assert route.call_count == 1
    assert sleeps == []


def test_resposta_fora_do_formato_gera_erro(client: PncpClient, api: respx.MockRouter) -> None:
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(200, json={"erro": "?"}))

    with pytest.raises(PncpError, match="resposta inesperada"):
        _collect(client)


def test_json_invalido_gera_erro(client: PncpClient, api: respx.MockRouter) -> None:
    api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(200, text="<html>manutenção</html>"))

    with pytest.raises(PncpError, match="JSON inválido"):
        _collect(client)


def test_sem_uf_consulta_o_brasil_inteiro(client: PncpClient, api: respx.MockRouter) -> None:
    route = api.get(PUBLISHED_PATH).mock(return_value=httpx.Response(204))

    list(client.iter_published(date(2026, 11, 17), date(2026, 11, 18), 6))

    assert "uf" not in route.calls.last.request.url.params


def test_respeita_intervalo_minimo_entre_requisicoes(api: respx.MockRouter) -> None:
    now = [100.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    api.get(PUBLISHED_PATH, params={"pagina": "1"}).mock(
        return_value=httpx.Response(200, json=PAGE_1)
    )
    api.get(PUBLISHED_PATH, params={"pagina": "2"}).mock(
        return_value=httpx.Response(200, json=PAGE_2)
    )
    client = PncpClient(BASE_URL, min_interval=1.5, sleep=fake_sleep, clock=lambda: now[0])

    pages = list(client.iter_published(date(2026, 11, 17), date(2026, 11, 18), 6, "MT"))

    assert len(pages) == 2
    assert sleeps == [1.5]  # a primeira requisição não espera; a segunda espera o intervalo
