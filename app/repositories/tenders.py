"""Acesso às contratações: gravação com upsert (INSERT ... ON CONFLICT) e consultas."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from app.models import Agency, Tender
from app.models.tender import SEARCH_CONFIG


@dataclass(frozen=True, slots=True)
class UpsertResult:
    new: int = 0
    updated: int = 0


def _dedupe(rows: Sequence[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Mantém a última ocorrência de cada chave.

    O ON CONFLICT não aceita a mesma chave duas vezes no mesmo comando, e a API pode
    repetir um registro quando a paginação "anda" durante a coleta.
    """
    return list({row[key]: row for row in rows}.values())


def upsert_agencies(session: Session, rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Insere ou atualiza órgãos pelo CNPJ e devolve {cnpj: id}."""
    rows = _dedupe(rows, "cnpj")
    if not rows:
        return {}
    stmt = insert(Agency).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Agency.cnpj],
        set_={
            "name": stmt.excluded.name,
            "sphere": stmt.excluded.sphere,
            "updated_at": func.now(),
        },
        # Só reescreve quando algo mudou, para updated_at continuar significativo.
        where=(Agency.name != stmt.excluded.name) | (Agency.sphere != stmt.excluded.sphere),
    )
    session.execute(stmt)
    cnpjs = [row["cnpj"] for row in rows]
    result = session.execute(select(Agency.cnpj, Agency.id).where(Agency.cnpj.in_(cnpjs)))
    return {cnpj: agency_id for cnpj, agency_id in result}


def upsert_tenders(session: Session, rows: Sequence[dict[str, Any]]) -> UpsertResult:
    """Insere novas contratações e atualiza as que mudaram, pelo número de controle do PNCP.

    "Mudou" = o JSON original (raw_data) é diferente do que está salvo; registros iguais
    não são tocados. O RETURNING com ``xmax = 0`` diferencia inserção de atualização.
    """
    rows = _dedupe(rows, "pncp_control_number")
    if not rows:
        return UpsertResult()
    stmt = insert(Tender).values(rows)
    updatable = [column for column in rows[0] if column != "pncp_control_number"]
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tender.pncp_control_number],
        set_={column: stmt.excluded[column] for column in updatable} | {"updated_at": func.now()},
        where=Tender.raw_data.is_distinct_from(stmt.excluded.raw_data),
    ).returning(literal_column("(xmax = 0)").label("inserted"))

    inserted_flags = session.execute(stmt).scalars().all()
    new = sum(1 for inserted in inserted_flags if inserted)
    return UpsertResult(new=new, updated=len(inserted_flags) - new)


# --- Consulta ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TenderQuery:
    """Critérios já resolvidos (datas convertidas para instantes UTC)."""

    text: str | None = None
    state: str | None = None
    municipality_ibge_code: str | None = None
    modality_code: int | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    published_since: datetime | None = None
    published_before: datetime | None = None
    open_at: datetime | None = None  # prazo de propostas ainda não encerrado neste instante


SEARCH_REGCONFIG = literal_column(f"'{SEARCH_CONFIG}'::regconfig")


def filter_conditions(query: TenderQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query.text:
        # websearch_to_tsquery aceita "frase exata", OR e -palavra, sem erro de sintaxe.
        tsquery = func.websearch_to_tsquery(SEARCH_REGCONFIG, query.text)
        # Busca só com palavras vazias ("de", "para") vira consulta vazia: não filtra.
        conditions.append(or_(func.numnode(tsquery) == 0, Tender.search_vector.op("@@")(tsquery)))
    if query.state:
        conditions.append(Tender.state == query.state)
    if query.municipality_ibge_code:
        conditions.append(Tender.municipality_ibge_code == query.municipality_ibge_code)
    if query.modality_code is not None:
        conditions.append(Tender.modality_code == query.modality_code)
    if query.min_value is not None:
        conditions.append(Tender.estimated_value >= query.min_value)
    if query.max_value is not None:
        conditions.append(Tender.estimated_value <= query.max_value)
    if query.published_since is not None:
        conditions.append(Tender.published_at >= query.published_since)
    if query.published_before is not None:
        conditions.append(Tender.published_at < query.published_before)
    if query.open_at is not None:
        # Inclui as que ainda vão abrir: também dá tempo de preparar a proposta.
        conditions.append(Tender.proposals_close_at > query.open_at)
    return conditions


def search_tenders(
    session: Session, query: TenderQuery, *, limit: int, offset: int
) -> tuple[list[Tender], int]:
    """Página de licitações (mais recentes primeiro) e o total que atende aos critérios."""
    conditions = filter_conditions(query)
    total = session.scalar(select(func.count()).select_from(Tender).where(*conditions)) or 0
    stmt = (
        select(Tender)
        .options(joinedload(Tender.agency))
        .where(*conditions)
        .order_by(Tender.published_at.desc(), Tender.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt)), total


def get_tender(session: Session, tender_id: int) -> Tender | None:
    stmt = select(Tender).options(joinedload(Tender.agency)).where(Tender.id == tender_id)
    return session.scalars(stmt).one_or_none()


def list_municipalities(session: Session, state: str | None = None) -> list[tuple[str, str]]:
    """(código IBGE, nome) dos municípios que têm licitações, em ordem alfabética."""
    stmt = (
        select(Tender.municipality_ibge_code, func.min(Tender.municipality_name).label("name"))
        .group_by(Tender.municipality_ibge_code)
        .order_by("name")
    )
    if state:
        stmt = stmt.where(Tender.state == state)
    return [(code, name) for code, name in session.execute(stmt)]


def list_states(session: Session) -> list[str]:
    """Siglas das UFs que têm licitações coletadas."""
    stmt = select(Tender.state).distinct().order_by(Tender.state)
    return list(session.scalars(stmt))
