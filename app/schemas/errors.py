"""Mensagens de validação do Pydantic em português (telas e respostas 422 da API)."""

from collections.abc import Mapping
from typing import Any

_MESSAGES: dict[str, str] = {
    "missing": "campo obrigatório",
    "string_pattern_mismatch": "formato inválido",
    "string_too_long": "texto longo demais (máximo de {max_length} caracteres)",
    "string_too_short": "texto curto demais (mínimo de {min_length} caracteres)",
    "int_parsing": "deve ser um número inteiro",
    "int_from_float": "deve ser um número inteiro",
    "decimal_parsing": "deve ser um número (use ponto como separador decimal)",
    "decimal_type": "deve ser um número",
    "float_parsing": "deve ser um número",
    "bool_parsing": "deve ser verdadeiro ou falso",
    "date_parsing": "data inválida (use AAAA-MM-DD)",
    "date_from_datetime_parsing": "data inválida (use AAAA-MM-DD)",
    "datetime_parsing": "data e hora inválidas",
    "greater_than_equal": "deve ser maior ou igual a {ge}",
    "greater_than": "deve ser maior que {gt}",
    "less_than_equal": "deve ser menor ou igual a {le}",
    "less_than": "deve ser menor que {lt}",
}


def translate_error(error: Mapping[str, Any]) -> str:
    """Mensagem em português para um item de ValidationError.errors()."""
    error_type = str(error.get("type", ""))
    if error_type == "value_error":  # nossos validadores já escrevem em português
        return str(error.get("msg", "")).removeprefix("Value error, ")
    template = _MESSAGES.get(error_type, "valor inválido")
    try:
        return template.format(**(error.get("ctx") or {}))
    except (KeyError, IndexError):
        return "valor inválido"
