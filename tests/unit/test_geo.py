from zoneinfo import ZoneInfo

import pytest

from app.api.templating import timezone_label
from app.geo import (
    STATES,
    MunicipalityNotFoundError,
    municipalities,
    municipality_in_state,
    municipality_label,
    normalize_name,
    resolve_municipality,
    state_name,
)


def test_27_ufs() -> None:
    assert len(STATES) == 27
    assert state_name("MT") == "Mato Grosso"
    assert state_name("??") == "??"


def test_municipio_pertence_a_uf_pelo_codigo_ibge() -> None:
    assert municipality_in_state("5107602", "MT")  # Rondonópolis
    assert not municipality_in_state("5107602", "SP")
    assert not municipality_in_state("5107602", "XX")


def test_rotulo_do_fuso() -> None:
    assert timezone_label(ZoneInfo("America/Sao_Paulo")) == "horário de Brasília"
    assert timezone_label(ZoneInfo("America/Cuiaba")) == "horário de Cuiabá"
    assert timezone_label(ZoneInfo("UTC")) == "fuso UTC"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rondonópolis", "5107602"),
        ("rondonopolis", "5107602"),
        ("  RONDONÓPOLIS / mt ", "5107602"),
        ("5107602", "5107602"),
        ("Pedra Preta/RN", "2409605"),
    ],
)
def test_resolve_municipio(text: str, expected: str) -> None:
    assert resolve_municipality(text) == expected


def test_nome_repetido_usa_as_ufs_preferidas() -> None:
    assert resolve_municipality("Pedra Preta", preferred_states=["MT"]) == "5106372"

    with pytest.raises(MunicipalityNotFoundError, match="Pedra Preta/MT, Pedra Preta/RN"):
        resolve_municipality("Pedra Preta")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Rondonopolys", "município não encontrado"),
        ("9999999", "código IBGE desconhecido"),
        ("Rondonópolis/XX", "UF desconhecida"),
        ("Rondonópolis/SP", "município não encontrado"),
    ],
)
def test_municipio_invalido(text: str, message: str) -> None:
    with pytest.raises(MunicipalityNotFoundError, match=message):
        resolve_municipality(text)


def test_lista_do_ibge() -> None:
    assert len(municipalities()) == 5571
    assert municipality_label("5106372") == "Pedra Preta/MT"
    assert municipality_label("123") == "123"
    assert normalize_name("  São   JOSÉ dos Quatro Marcos ") == "sao jose dos quatro marcos"
