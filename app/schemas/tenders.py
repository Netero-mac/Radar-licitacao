"""Filtros de busca e formatos de resposta das licitações (telas e API JSON)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    computed_field,
    model_validator,
)
from pydantic_core import PydanticUseDefault

from app.geo import STATES
from app.models import Sphere
from app.schemas.errors import translate_error

MAX_PAGE_SIZE = 100


def _blank_to_default(value: Any) -> Any:
    """Formulários HTML mandam campos vazios como "": o campo fica com o valor padrão."""
    if isinstance(value, str) and not value.strip():
        raise PydanticUseDefault
    return value


def _parse_bool(value: Any) -> Any:
    # Checkbox desmarcado não é enviado; marcado envia "on" (ou "1", "true"...).
    if isinstance(value, str) and value.strip().lower() in {"on", "sim"}:
        return True
    return _blank_to_default(value)


BlankAsDefault = BeforeValidator(_blank_to_default)


def _check_state(value: str) -> str:
    value = value.upper()
    if value not in STATES:
        raise ValueError("UF desconhecida")
    return value


StateCode = Annotated[str, AfterValidator(_check_state)]

# Restrição no próprio str (e não no "str | None") para o erro sair como "string_too_long".
SearchText = Annotated[str, StringConstraints(max_length=200)]


class TenderFilters(BaseModel):
    """Filtros da listagem. Todos são opcionais e combinados com E."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    q: Annotated[
        SearchText | None,
        BlankAsDefault,
        Field(description='Busca no objeto. Ignora acentos; aceita "frase exata", OR e -exclusão.'),
    ] = None
    state: Annotated[StateCode | None, BlankAsDefault, Field(description="UF (sigla, ex.: MT)")] = (
        None
    )
    municipality: Annotated[
        str | None,
        BlankAsDefault,
        Field(pattern=r"^\d{7}$", description="Código IBGE do município (7 dígitos)"),
    ] = None
    modality: Annotated[
        int | None, BlankAsDefault, Field(ge=1, description="Código da modalidade de contratação")
    ] = None
    min_value: Annotated[
        Decimal | None, BlankAsDefault, Field(ge=0, description="Valor estimado mínimo (R$)")
    ] = None
    max_value: Annotated[
        Decimal | None, BlankAsDefault, Field(ge=0, description="Valor estimado máximo (R$)")
    ] = None
    published_from: Annotated[
        date | None, BlankAsDefault, Field(description="Publicadas a partir de (AAAA-MM-DD)")
    ] = None
    published_to: Annotated[
        date | None, BlankAsDefault, Field(description="Publicadas até (AAAA-MM-DD, inclusive)")
    ] = None
    open_only: Annotated[
        bool,
        BeforeValidator(_parse_bool),
        Field(description="Somente com prazo de propostas não encerrado (inclui as que vão abrir)"),
    ] = False
    page: Annotated[int, BlankAsDefault, Field(ge=1, description="Página (começa em 1)")] = 1
    page_size: Annotated[
        int, BlankAsDefault, Field(ge=1, le=MAX_PAGE_SIZE, description="Itens por página")
    ] = 20

    @model_validator(mode="after")
    def _check_ranges(self) -> Self:
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("o valor mínimo não pode ser maior que o máximo")
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            raise ValueError("a data inicial não pode ser posterior à data final")
        return self

    @classmethod
    def from_query_lenient(cls, params: dict[str, Any]) -> tuple[Self, list[str]]:
        """Para as telas: em vez de erro 422, ignora o filtro inválido e explica o motivo."""
        data = dict(params)
        errors: list[str] = []
        for _ in range(len(cls.model_fields) + 1):
            try:
                return cls.model_validate(data), errors
            except ValidationError as exc:
                for error in exc.errors():
                    field = str(error["loc"][0]) if error["loc"] else None
                    label = FIELD_LABELS.get(field or "", "Filtro")
                    errors.append(f"{label}: {translate_error(error)}")
                    if field:
                        data.pop(field, None)
                    else:  # erro entre campos (faixa invertida): descarta a faixa
                        for pair in (
                            ("min_value", "max_value"),
                            ("published_from", "published_to"),
                        ):
                            if all(data.get(name) for name in pair):
                                data.pop(pair[1], None)
                                break
        return cls(), errors  # pragma: no cover - salvaguarda

    def query_params(self, **overrides: Any) -> dict[str, str]:
        """Parâmetros de URL dos filtros ativos (para links de paginação)."""
        values = self.model_dump() | overrides
        params: dict[str, str] = {}
        for key, value in values.items():
            if value is None or value is False:
                continue
            if key == "page" and value == 1:
                continue
            if key == "page_size" and value == TenderFilters.model_fields["page_size"].default:
                continue
            params[key] = "on" if value is True else str(value)
        return params

    @property
    def is_filtered(self) -> bool:
        return bool(self.query_params(page=1))


FIELD_LABELS = {
    "q": "Busca",
    "state": "UF",
    "municipality": "Município",
    "modality": "Modalidade",
    "min_value": "Valor mínimo",
    "max_value": "Valor máximo",
    "published_from": "Publicadas a partir de",
    "published_to": "Publicadas até",
    "open_only": "Propostas abertas",
    "page": "Página",
    "page_size": "Itens por página",
}


class AgencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cnpj: str
    name: str
    sphere: Sphere


class TenderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pncp_control_number: str
    object_description: str
    agency_name: str
    municipality_name: str
    municipality_ibge_code: str
    state: str
    modality_code: int
    modality_name: str
    status: str
    estimated_value: Decimal | None
    published_at: datetime
    proposals_open_at: datetime | None
    proposals_close_at: datetime | None
    proposals_open: bool = Field(description="Prazo de propostas ainda não encerrado")
    source_url: str


class TenderDetail(TenderSummary):
    agency: AgencyOut
    unit_name: str | None
    status_code: int
    pncp_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Extraídos do registro original do PNCP (raw_data)
    process_number: str | None = None
    legal_basis: str | None = None
    dispute_mode: str | None = None
    complementary_info: str | None = None
    origin_system_url: str | None = Field(
        default=None, description="Link do sistema de compras usado pelo órgão"
    )


class TenderPage(BaseModel):
    items: list[TenderSummary]
    total: int
    page: int
    page_size: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))
