"""Falhas no envio dos resumos em cada execução (collection_runs.notification_failures).

Nulo = a execução não enviou resumos (botão "Coletar agora" e CLI).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "collection_runs", sa.Column("notification_failures", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("collection_runs", "notification_failures")
