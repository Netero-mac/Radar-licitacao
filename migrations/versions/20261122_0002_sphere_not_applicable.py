"""Esfera "não se aplica" (esferaId = N no PNCP).

Entidades como consórcios públicos e serviços sociais publicam no PNCP sem pertencer a
uma esfera de governo; sem este valor, as contratações delas seriam descartadas.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE agency_sphere ADD VALUE IF NOT EXISTS 'nao_se_aplica'")


def downgrade() -> None:
    # O PostgreSQL não remove valores de enum: recria o tipo sem ele. Falha de propósito
    # se ainda houver órgãos com essa esfera, para não perder dados em silêncio.
    op.execute("ALTER TYPE agency_sphere RENAME TO agency_sphere_old")
    op.execute(
        "CREATE TYPE agency_sphere AS ENUM ('municipal', 'estadual', 'federal', 'distrital')"
    )
    op.execute(
        "ALTER TABLE agencies ALTER COLUMN sphere TYPE agency_sphere "
        "USING sphere::text::agency_sphere"
    )
    op.execute("DROP TYPE agency_sphere_old")
