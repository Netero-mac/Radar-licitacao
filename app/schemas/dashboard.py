"""Filtros e respostas do painel (/painel e /api/dashboard/*)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from app.schemas.errors import translate_error
from app.schemas.tenders import BlankAsDefault, StateCode

PERIOD_MONTHS = (3, 6, 12, 24)
DEFAULT_MONTHS = 12
MAX_RANKING = 50


def _check_months(value: int) -> int:
    if value not in PERIOD_MONTHS:
        raise ValueError("escolha 3, 6, 12 ou 24 meses")
    return value


# int + validação (e não Literal): a query string chega como texto e precisa ser convertida.
Months = Annotated[int, AfterValidator(_check_months)]

FIELD_LABELS = {"state": "UF", "months": "Período", "limit": "Quantidade", "order": "Ordem"}


class DashboardFilters(BaseModel):
    """O painel cobre os últimos N meses (o mês atual conta como um deles)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    state: Annotated[StateCode | None, BlankAsDefault, Field(description="UF (sigla, ex.: MT)")] = (
        None
    )
    months: Annotated[
        Months,
        BlankAsDefault,
        Field(description="Período: últimos 3, 6, 12 ou 24 meses, incluindo o mês atual"),
    ] = DEFAULT_MONTHS

    @classmethod
    def from_query_lenient(cls, params: dict[str, Any]) -> tuple[Self, list[str]]:
        """Para a tela: filtro inválido é ignorado (volta ao padrão) com uma explicação."""
        data = {name: params[name] for name in cls.model_fields if name in params}
        try:
            return cls.model_validate(data), []
        except ValidationError as exc:
            errors = []
            for error in exc.errors():
                field = str(error["loc"][0])
                errors.append(f"{FIELD_LABELS.get(field, 'Filtro')}: {translate_error(error)}")
                data.pop(field, None)
            return cls.model_validate(data), errors

    def query_params(self) -> dict[str, str]:
        params = {"months": str(self.months)}
        if self.state:
            params["state"] = self.state
        return params


class RankingParams(BaseModel):
    order: Annotated[
        Literal["tenders", "value"],
        Field(description="`tenders` (quantidade) ou `value` (valor estimado)"),
    ] = "tenders"
    limit: Annotated[int, Field(ge=1, le=MAX_RANKING, description="Quantos municípios")] = 15


class Period(BaseModel):
    start: date = Field(description="Primeiro dia do período (fuso de exibição)")
    end: date = Field(description="Hoje (fuso de exibição); o mês atual ainda está em andamento")
    months: int


class Summary(BaseModel):
    period: Period
    tenders: int
    total_value: Decimal = Field(description="Soma dos valores estimados informados")
    without_value: int = Field(description="Licitações sem valor estimado (fora da soma)")
    secret_value: int = Field(
        description="Licitações com valor zero, que no PNCP indica orçamento sigiloso"
    )
    open_now: int = Field(description="Ainda recebendo propostas")
    municipalities: int


class Stat(BaseModel):
    """Um item de gráfico: rótulo, quantidade de licitações e soma do valor estimado."""

    key: str
    label: str
    tenders: int
    total_value: Decimal


class MunicipalityStat(Stat):
    state: str


class MunicipalityRanking(BaseModel):
    period: Period
    order: Literal["tenders", "value"]
    items: list[MunicipalityStat]
    total_municipalities: int


class CategoryStat(Stat):
    keywords: list[str] = Field(description="Termos que definem a categoria")


class CategoryBreakdown(BaseModel):
    period: Period
    items: list[CategoryStat] = Field(description="Maior quantidade primeiro")
    uncategorized: Stat
    total_tenders: int
    note: str = (
        "Uma licitação pode entrar em mais de uma categoria; a soma das categorias pode "
        "passar do total."
    )


class MonthStat(Stat):
    month: date = Field(description="Primeiro dia do mês")
    partial: bool = Field(description="Mês atual, ainda em andamento")


class MonthlySeries(BaseModel):
    period: Period
    items: list[MonthStat] = Field(description="Todos os meses do período, inclusive sem dados")
