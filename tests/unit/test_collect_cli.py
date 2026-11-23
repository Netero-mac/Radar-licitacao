from datetime import date
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app import collect
from app.config import DEFAULT_MODALITIES, Settings
from app.models import CollectionStatus, CollectionTrigger
from app.services.collection import default_period

CUIABA = ZoneInfo("America/Cuiaba")


def test_le_periodo_da_linha_de_comando() -> None:
    args = collect.build_parser().parse_args(["--from", "2026-11-01", "--to", "2026-11-22"])

    assert args.date_from == date(2026, 11, 1)
    assert args.date_to == date(2026, 11, 22)
    assert args.modalities is None


def test_le_modalidades() -> None:
    args = collect.build_parser().parse_args(["--modalidades", "6, 8"])

    assert args.modalities == [6, 8]


@pytest.mark.parametrize(
    "argv", [["--from", "22/11/2026"], ["--modalidades", "99"], ["--modalidades", "seis"]]
)
def test_rejeita_argumentos_invalidos(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        collect.build_parser().parse_args(argv)


def test_periodo_padrao_sao_os_ultimos_n_dias() -> None:
    date_from, date_to = default_period(2, CUIABA)

    assert (date_to - date_from).days == 1


def test_resolve_periodo_completa_datas_ausentes() -> None:
    assert collect.resolve_period(date(2026, 11, 1), date(2026, 11, 5), 2, CUIABA) == (
        date(2026, 11, 1),
        date(2026, 11, 5),
    )
    # Só --to no passado: começa no próprio --to, em vez de gerar um período invertido.
    assert collect.resolve_period(None, date(2020, 1, 10), 2, CUIABA) == (
        date(2020, 1, 10),
        date(2020, 1, 10),
    )


def test_main_executa_coleta_e_retorna_codigo(monkeypatch: pytest.MonkeyPatch) -> None:
    run = MagicMock(status=CollectionStatus.SUCCESS)
    run_collection = MagicMock(return_value=run)
    monkeypatch.setattr(collect, "run_collection", run_collection)
    monkeypatch.setattr(collect, "get_sessionmaker", lambda: MagicMock())
    monkeypatch.setattr(collect, "PncpClient", MagicMock())
    match_new_tenders = MagicMock()
    monkeypatch.setattr(collect, "match_new_tenders", match_new_tenders)

    assert collect.main(["--from", "2026-11-01", "--to", "2026-11-22"]) == 0
    # depois da coleta, as licitações novas são cruzadas com os alertas
    assert match_new_tenders.call_args.kwargs == {"created_since": run.started_at}

    kwargs = run_collection.call_args.kwargs
    assert kwargs["date_from"] == date(2026, 11, 1)
    assert kwargs["date_to"] == date(2026, 11, 22)
    assert kwargs["trigger"] == CollectionTrigger.CLI
    assert kwargs["states"] == ["MT"]

    run.status = CollectionStatus.FAILED
    assert collect.main(["--ufs", "br"]) == 1
    assert run_collection.call_args.kwargs["states"] == []


def test_main_rejeita_periodo_invertido() -> None:
    with pytest.raises(SystemExit):
        collect.main(["--from", "2026-11-22", "--to", "2026-11-01"])


def test_modalidades_aceitam_lista_separada_por_virgula() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x", pncp_modalities="6, 8,4")  # type: ignore[arg-type]

    assert settings.pncp_modalities == [6, 8, 4]
    assert (
        Settings(_env_file=None, database_url="postgresql://x").pncp_modalities
        == DEFAULT_MODALITIES
    )


def test_le_ufs() -> None:
    parser = collect.build_parser()

    assert parser.parse_args(["--ufs", "mt, ms"]).states == ["MT", "MS"]
    assert parser.parse_args(["--ufs", "BR"]).states == []
    assert parser.parse_args([]).states is None
    with pytest.raises(SystemExit):
        parser.parse_args(["--ufs", "XX"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [("MT", ["MT"]), ("mt, ms,MT", ["MT", "MS"]), ("", []), ("BR", [])],
)
def test_ufs_configuradas(value: str, expected: list[str]) -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x", pncp_states=value)  # type: ignore[arg-type]

    assert settings.pncp_states == expected


def test_uf_desconhecida_na_configuracao() -> None:
    with pytest.raises(ValueError, match="UF desconhecida: XX"):
        Settings(_env_file=None, database_url="postgresql://x", pncp_states="MT,XX")  # type: ignore[arg-type]


def test_padroes_de_uf_e_fuso() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x")  # type: ignore[call-arg]

    assert settings.pncp_states == ["MT"]
    assert settings.display_timezone == "America/Sao_Paulo"
