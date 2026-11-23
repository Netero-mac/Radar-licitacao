"""Formulário de alerta (cadastro/edição na área administrativa)."""

import re
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticUseDefault

from app.geo import STATES, MunicipalityNotFoundError, resolve_municipality
from app.schemas.errors import translate_error

MAX_KEYWORDS = 30
MAX_MUNICIPALITIES = 100
# Validação simples de propósito: o servidor SMTP é quem dá a palavra final.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TELEGRAM_CHAT = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")


def _blank_to_default(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        raise PydanticUseDefault
    return value


def _lines(value: Any) -> Any:
    """Textarea -> lista: uma entrada por linha."""
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return value


BlankAsDefault = BeforeValidator(_blank_to_default)


class AlertForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=120)]
    email: Annotated[str, Field(max_length=254)]
    keywords: Annotated[list[str], BeforeValidator(_lines)]
    states: list[str] = []
    municipalities: list[str] = []
    min_value: Annotated[Decimal | None, BlankAsDefault, Field(ge=0, max_digits=16)] = None
    max_value: Annotated[Decimal | None, BlankAsDefault, Field(ge=0, max_digits=16)] = None
    telegram_chat_id: Annotated[str | None, BlankAsDefault] = None
    active: bool = True

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        if not _EMAIL.match(value):
            raise ValueError("e-mail inválido")
        return value.lower()

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, value: list[str]) -> list[str]:
        # Sem repetição (ignorando maiúsculas), mantendo a primeira forma digitada.
        first: dict[str, str] = {}
        for keyword in value:
            first.setdefault(keyword.casefold(), keyword)
        unique = list(first.values())
        if not unique:
            raise ValueError("informe ao menos uma palavra-chave")
        if len(unique) > MAX_KEYWORDS:
            raise ValueError(f"no máximo {MAX_KEYWORDS} palavras-chave")
        too_long = [keyword for keyword in unique if len(keyword) > 120]
        if too_long:
            raise ValueError("cada palavra-chave pode ter até 120 caracteres")
        return unique

    @field_validator("states")
    @classmethod
    def _check_states(cls, value: list[str]) -> list[str]:
        states = list(dict.fromkeys(state.strip().upper() for state in value if state.strip()))
        unknown = [state for state in states if state not in STATES]
        if unknown:
            raise ValueError(f"UF desconhecida: {', '.join(unknown)}")
        return states

    @field_validator("municipalities", mode="before")
    @classmethod
    def _split_municipalities(cls, value: Any) -> Any:
        """Um por linha, ou separados por vírgula/ponto e vírgula."""
        if isinstance(value, str):
            return _lines(value.replace(",", "\n").replace(";", "\n"))
        return value

    @field_validator("municipalities")
    @classmethod
    def _resolve_municipalities(cls, value: list[str], info: ValidationInfo) -> list[str]:
        """Nomes -> códigos IBGE. As UFs coletadas desempatam nomes repetidos."""
        preferred = (info.context or {}).get("preferred_states", ())
        codes: list[str] = []
        problems: list[str] = []
        for entry in value:
            try:
                codes.append(resolve_municipality(entry, preferred))
            except MunicipalityNotFoundError as exc:
                problems.append(str(exc))
        if problems:
            raise ValueError("; ".join(problems))
        if len(set(codes)) > MAX_MUNICIPALITIES:
            raise ValueError(f"no máximo {MAX_MUNICIPALITIES} municípios")
        return list(dict.fromkeys(codes))

    @field_validator("telegram_chat_id")
    @classmethod
    def _check_chat(cls, value: str | None) -> str | None:
        if value is not None and not _TELEGRAM_CHAT.match(value):
            raise ValueError("use o número do chat (ex.: 123456789) ou @nome_do_canal")
        return value

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("o valor mínimo não pode ser maior que o máximo")
        return self

    @classmethod
    def parse(
        cls, data: dict[str, Any], preferred_states: list[str]
    ) -> tuple[Self | None, dict[str, str]]:
        """Valida o formulário; em caso de erro devolve {campo: mensagem em português}."""
        try:
            return cls.model_validate(data, context={"preferred_states": preferred_states}), {}
        except ValidationError as exc:
            errors: dict[str, str] = {}
            for error in exc.errors():
                field = str(error["loc"][0]) if error["loc"] else "__all__"
                errors.setdefault(field, translate_error(error))
            return None, errors
