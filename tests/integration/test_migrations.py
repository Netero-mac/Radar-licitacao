from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.models import Base
from tests.integration.conftest import TEST_DATABASE_URL, alembic_config


def test_migration_cria_todas_as_tabelas(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())

    assert {"agencies", "tenders", "alerts", "alert_matches", "collection_runs"} <= tables


def test_models_e_migrations_estao_sincronizados(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "include_object": lambda o, n, t, r, c: n != "ix_tenders_search_vector",
            },
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == []


def test_busca_textual_ignora_acentos(migrated_engine: Engine) -> None:
    query = text("SELECT to_tsvector('pt_unaccent', :doc) @@ plainto_tsquery('pt_unaccent', :q)")
    doc = "Contratação de MANUTENÇÃO preventiva de equipamentos de informática"
    with migrated_engine.connect() as conn:
        assert conn.execute(query, {"doc": doc, "q": "manutencao"}).scalar() is True
        assert conn.execute(query, {"doc": doc, "q": "equipamento"}).scalar() is True
        assert conn.execute(query, {"doc": doc, "q": "pavimentação"}).scalar() is False


def test_downgrade_e_upgrade_ida_e_volta(migrated_engine: Engine) -> None:
    config = alembic_config(TEST_DATABASE_URL or "")

    command.downgrade(config, "base")
    assert "tenders" not in inspect(migrated_engine).get_table_names()

    command.upgrade(config, "head")
    assert "tenders" in inspect(migrated_engine).get_table_names()
