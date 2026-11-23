"""Marca de envio pelo Telegram, separada da do e-mail (alert_matches.notified_at).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert_matches",
        sa.Column("telegram_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alert_matches", "telegram_notified_at")
