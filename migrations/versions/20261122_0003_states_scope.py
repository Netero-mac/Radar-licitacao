"""Abrangência por UF: alerts.states e collection_runs.states.

Permite coletar e alertar sobre outras UFs além de MT (PNCP_STATES).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _states_column() -> sa.Column:
    return sa.Column(
        "states",
        postgresql.ARRAY(sa.String(length=2)),
        server_default=sa.text("'{}'"),
        nullable=False,
    )


def upgrade() -> None:
    op.add_column("alerts", _states_column())
    op.add_column("collection_runs", _states_column())


def downgrade() -> None:
    op.drop_column("collection_runs", "states")
    op.drop_column("alerts", "states")
