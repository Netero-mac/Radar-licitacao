from zoneinfo import ZoneInfo

from app.api.templating import timezone_label
from app.geo import STATES, municipality_in_state, state_name


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
