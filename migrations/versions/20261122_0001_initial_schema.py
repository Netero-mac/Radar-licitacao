"""Esquema inicial: órgãos, licitações, alertas e execuções da coleta.

Revision ID: 0001
Revises:
Create Date: 2026-11-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

sphere = postgresql.ENUM(
    "municipal", "estadual", "federal", "distrital", name="agency_sphere", create_type=False
)
run_status = postgresql.ENUM(
    "running", "success", "failed", name="collection_status", create_type=False
)
run_trigger = postgresql.ENUM(
    "scheduled", "manual", "cli", name="collection_trigger", create_type=False
)

TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)


def upgrade() -> None:
    # Busca textual em português ignorando acentos ("manutencao" encontra "manutenção").
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE TEXT SEARCH CONFIGURATION pt_unaccent (COPY = pg_catalog.portuguese)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION pt_unaccent "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem"
    )

    bind = op.get_bind()
    for enum in (sphere, run_status, run_trigger):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "agencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sphere", sphere, nullable=False),
        *(c.copy() for c in TIMESTAMPS),
        sa.PrimaryKeyConstraint("id", name="pk_agencies"),
        sa.UniqueConstraint("cnpj", name="uq_agencies_cnpj"),
    )

    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pncp_control_number", sa.String(50), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("unit_name", sa.String(255), nullable=True),
        sa.Column("municipality_name", sa.String(120), nullable=False),
        sa.Column("municipality_ibge_code", sa.String(7), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("object_description", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('pt_unaccent'::regconfig, coalesce(object_description, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("modality_code", sa.Integer(), nullable=False),
        sa.Column("modality_name", sa.String(120), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("estimated_value", sa.Numeric(18, 4), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposals_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposals_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pncp_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        *(c.copy() for c in TIMESTAMPS),
        sa.PrimaryKeyConstraint("id", name="pk_tenders"),
        sa.UniqueConstraint("pncp_control_number", name="uq_tenders_pncp_control_number"),
        sa.ForeignKeyConstraint(
            ["agency_id"], ["agencies.id"], name="fk_tenders_agency_id_agencies",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_tenders_municipality_ibge_code", "tenders", ["municipality_ibge_code"])
    op.create_index("ix_tenders_state", "tenders", ["state"])
    op.create_index("ix_tenders_modality_code", "tenders", ["modality_code"])
    op.create_index("ix_tenders_published_at", "tenders", ["published_at"])
    op.create_index("ix_tenders_proposals_close_at", "tenders", ["proposals_close_at"])
    op.create_index(
        "ix_tenders_search_vector", "tenders", ["search_vector"], postgresql_using="gin"
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("keywords", postgresql.ARRAY(sa.String(120)), nullable=False),
        sa.Column(
            "municipalities", postgresql.ARRAY(sa.String(7)),
            server_default=sa.text("'{}'"), nullable=False,
        ),
        sa.Column("min_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *(c.copy() for c in TIMESTAMPS),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_alerts_value_range",
        ),
        sa.CheckConstraint("cardinality(keywords) > 0", name="ck_alerts_has_keywords"),
    )

    op.create_table(
        "alert_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column(
            "matched_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_alert_matches"),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name="fk_alert_matches_alert_id_alerts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name="fk_alert_matches_tender_id_tenders",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("alert_id", "tender_id", name="uq_alert_matches_alert_id_tender_id"),
    )
    op.create_index("ix_alert_matches_tender_id", "alert_matches", ["tender_id"])

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", run_status, server_default="running", nullable=False),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tenders_new", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tenders_updated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_collection_runs"),
    )
    op.create_index("ix_collection_runs_started_at", "collection_runs", ["started_at"])


def downgrade() -> None:
    op.drop_table("collection_runs")
    op.drop_table("alert_matches")
    op.drop_table("alerts")
    op.drop_table("tenders")
    op.drop_table("agencies")
    bind = op.get_bind()
    for enum in (run_trigger, run_status, sphere):
        enum.drop(bind, checkfirst=True)
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS pt_unaccent")
    # A extensão unaccent é mantida: pode estar em uso por outros objetos do banco.
