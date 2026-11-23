"""Formato das respostas da API de consulta do PNCP e conversão para o nosso modelo.

Só validamos os campos que usamos; o registro original inteiro vai para tenders.raw_data.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.enums import Sphere

EDITAL_URL = "https://pncp.gov.br/app/editais/{cnpj}/{year}/{sequence}"

# esferaId do PNCP -> nossa esfera
SPHERES = {
    "M": Sphere.MUNICIPAL,
    "E": Sphere.STATE,
    "F": Sphere.FEDERAL,
    "D": Sphere.DISTRICT,
    "N": Sphere.NOT_APPLICABLE,
}


class _PncpModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class PncpAgency(_PncpModel):
    cnpj: str = Field(min_length=14, max_length=14)
    razao_social: str
    esfera_id: str


class PncpUnit(_PncpModel):
    uf_sigla: str
    municipio_nome: str
    codigo_ibge: str = Field(min_length=7, max_length=7)
    nome_unidade: str | None = None


class PncpTender(_PncpModel):
    """Um item de "data" nas respostas de /v1/contratacoes/*."""

    numero_controle_pncp: str = Field(alias="numeroControlePNCP")
    orgao_entidade: PncpAgency
    unidade_orgao: PncpUnit
    ano_compra: int
    sequencial_compra: int
    objeto_compra: str
    modalidade_id: int
    modalidade_nome: str
    situacao_compra_id: int
    situacao_compra_nome: str
    valor_total_estimado: Decimal | None = None
    # A API manda datas sem fuso (horário de Brasília); a conversão para UTC é feita abaixo.
    data_publicacao_pncp: datetime
    data_abertura_proposta: datetime | None = None
    data_encerramento_proposta: datetime | None = None
    data_atualizacao_global: datetime | None = None

    def sphere(self) -> Sphere:
        try:
            return SPHERES[self.orgao_entidade.esfera_id]
        except KeyError:
            raise ValueError(f"esfera desconhecida: {self.orgao_entidade.esfera_id!r}") from None

    def source_url(self) -> str:
        return EDITAL_URL.format(
            cnpj=self.orgao_entidade.cnpj, year=self.ano_compra, sequence=self.sequencial_compra
        )


@dataclass(frozen=True, slots=True)
class PncpPage:
    number: int
    total_pages: int
    total_records: int
    remaining_pages: int
    items: list[dict[str, Any]]


def to_utc(value: datetime | None, source_tz: ZoneInfo) -> datetime | None:
    """Datas sem fuso são interpretadas no fuso da API; datas com fuso são respeitadas."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=source_tz)
    return value.astimezone(UTC)


def agency_values(tender: PncpTender) -> dict[str, Any]:
    return {
        "cnpj": tender.orgao_entidade.cnpj,
        "name": tender.orgao_entidade.razao_social.strip(),
        "sphere": tender.sphere(),
    }


def tender_values(
    tender: PncpTender, raw: dict[str, Any], agency_id: int, source_tz: ZoneInfo
) -> dict[str, Any]:
    """Colunas de `tenders` (exceto id e timestamps) a partir de um item da API."""
    unit = tender.unidade_orgao
    return {
        "pncp_control_number": tender.numero_controle_pncp,
        "agency_id": agency_id,
        "unit_name": unit.nome_unidade,
        "municipality_name": unit.municipio_nome,
        "municipality_ibge_code": unit.codigo_ibge,
        "state": unit.uf_sigla.upper(),
        "object_description": tender.objeto_compra.strip(),
        "modality_code": tender.modalidade_id,
        "modality_name": tender.modalidade_nome,
        "status_code": tender.situacao_compra_id,
        "status": tender.situacao_compra_nome,
        "estimated_value": tender.valor_total_estimado,
        "published_at": to_utc(tender.data_publicacao_pncp, source_tz),
        "proposals_open_at": to_utc(tender.data_abertura_proposta, source_tz),
        "proposals_close_at": to_utc(tender.data_encerramento_proposta, source_tz),
        "pncp_updated_at": to_utc(tender.data_atualizacao_global, source_tz),
        "source_url": tender.source_url(),
        "raw_data": raw,
    }
