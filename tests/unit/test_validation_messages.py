import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.errors import translate_error
from app.schemas.tenders import TenderFilters


def _first_error(data: dict[str, str]) -> str:
    with pytest.raises(ValidationError) as exc_info:
        TenderFilters.model_validate(data)
    return translate_error(exc_info.value.errors()[0])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"municipality": "abc"}, "formato inválido"),
        ({"modality": "seis"}, "deve ser um número inteiro"),
        ({"min_value": "dez"}, "deve ser um número (use ponto como separador decimal)"),
        ({"published_from": "22/11/2026"}, "data inválida (use AAAA-MM-DD)"),
        ({"page": "0"}, "deve ser maior ou igual a 1"),
        ({"page_size": "101"}, "deve ser menor ou igual a 100"),
        ({"q": "x" * 201}, "texto longo demais (máximo de 200 caracteres)"),
        ({"min_value": "9", "max_value": "1"}, "o valor mínimo não pode ser maior que o máximo"),
    ],
)
def test_mensagens_em_portugues(data: dict[str, str], message: str) -> None:
    assert _first_error(data) == message


def test_tipo_desconhecido_tem_mensagem_generica() -> None:
    assert translate_error({"type": "algo_novo", "msg": "Something"}) == "valor inválido"
    assert translate_error({"type": "greater_than_equal", "ctx": {}}) == "valor inválido"


def test_erro_422_da_api_vem_em_portugues() -> None:
    # A validação dos parâmetros acontece antes de qualquer acesso ao banco.
    response = TestClient(create_app()).get("/api/tenders", params={"municipality": "abc"})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "string_pattern_mismatch",
                "loc": ["query", "municipality"],
                "msg": "formato inválido",
            }
        ]
    }
