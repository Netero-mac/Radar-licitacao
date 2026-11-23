from decimal import Decimal
from typing import Any

import pytest

from app.schemas.alerts import AlertForm

VALID: dict[str, Any] = {
    "name": "TI em Rondonópolis",
    "email": "Compras@Empresa.com.br",
    "keywords": "manutenção de computadores\n\n impressora \nIMPRESSORA\n",
    "states": [],
    "municipalities": "",
    "min_value": "",
    "max_value": "",
    "telegram_chat_id": "",
    "active": True,
}


def _parse(**overrides: Any) -> tuple[AlertForm | None, dict[str, str]]:
    return AlertForm.parse({**VALID, **overrides}, preferred_states=["MT"])


def test_formulario_valido() -> None:
    form, errors = _parse()

    assert errors == {}
    assert form is not None
    assert form.email == "compras@empresa.com.br"
    assert form.keywords == ["manutenção de computadores", "impressora"]  # sem repetição
    assert form.min_value is None
    assert form.telegram_chat_id is None


def test_municipios_por_nome_virgula_ou_linha() -> None:
    form, errors = _parse(municipalities="Rondonópolis, pedra preta\nJaciara; Rondonópolis")

    assert errors == {}
    assert form is not None
    # Pedra Preta existe em MT e RN: as UFs coletadas (MT) desempatam
    assert form.municipalities == ["5107602", "5106372", "5104807"]


def test_ufs_e_faixa_de_valor() -> None:
    form, errors = _parse(states=["mt", "MS", "MT"], min_value="1000", max_value="250000.50")

    assert errors == {}
    assert form is not None
    assert form.states == ["MT", "MS"]
    assert (form.min_value, form.max_value) == (Decimal("1000"), Decimal("250000.50"))


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"name": "  "}, "name", "texto curto demais"),
        ({"email": "compras.empresa.com"}, "email", "e-mail inválido"),
        ({"keywords": " \n "}, "keywords", "informe ao menos uma palavra-chave"),
        ({"keywords": "x" * 121}, "keywords", "até 120 caracteres"),
        ({"keywords": "\n".join(f"p{i}" for i in range(31))}, "keywords", "no máximo 30"),
        ({"municipalities": "Rondonopolys"}, "municipalities", "município não encontrado"),
        ({"states": ["XX"]}, "states", "UF desconhecida: XX"),
        ({"min_value": "abc"}, "min_value", "deve ser um número"),
        ({"min_value": "-5"}, "min_value", "maior ou igual a 0"),
        ({"telegram_chat_id": "meu chat"}, "telegram_chat_id", "número do chat"),
        ({"min_value": "500", "max_value": "100"}, "__all__", "valor mínimo não pode"),
    ],
)
def test_erros_em_portugues_por_campo(overrides: dict[str, Any], field: str, message: str) -> None:
    form, errors = _parse(**overrides)

    assert form is None
    assert message in errors[field]


def test_chat_do_telegram_aceita_numero_ou_canal() -> None:
    assert _parse(telegram_chat_id="-1001234567890")[0] is not None
    assert _parse(telegram_chat_id="@radar_licitacoes")[0] is not None
