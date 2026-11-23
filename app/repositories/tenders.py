"""Gravação de órgãos e contratações com upsert (INSERT ... ON CONFLICT do PostgreSQL)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Agency, Tender


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
