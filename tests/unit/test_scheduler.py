from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app import scheduler
from app.config import Settings
from app.models import CollectionStatus, CollectionTrigger
from app.services.notifications import DigestReport
from app.services.pipeline import PipelineResult


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://x", **overrides)  # type: ignore[arg-type]


def test_horarios_padrao_e_do_env() -> None:
    assert _settings().schedule_hours == [7, 18]
    assert _settings().schedule_timezone == "America/Cuiaba"
    assert _settings(schedule_hours="18, 6,6").schedule_hours == [6, 18]
    with pytest.raises(ValueError, match="entre 0 e 23"):
        _settings(schedule_hours="7,25")


def test_proximos_horarios_no_fuso_do_agendamento() -> None:
    # 22/11 15:00 UTC = 11:00 em Cuiabá: próximo é 18h de hoje, depois 7h de amanhã
    runs = scheduler.next_scheduled_runs(_settings(), datetime(2026, 11, 22, 15, tzinfo=UTC))

    assert [run.strftime("%d/%m %H:%M") for run in runs] == ["22/11 18:00", "23/11 07:00"]
    assert runs[0].astimezone(UTC).hour == 22  # 18h em Cuiabá (UTC-4)


def test_job_configurado_sem_acumular_execucoes() -> None:
    job = scheduler.build_scheduler(_settings(schedule_hours="7")).get_job(scheduler.JOB_ID)

    assert job.coalesce is True
    assert job.max_instances == 1
    assert job.misfire_grace_time == scheduler.MISFIRE_GRACE_SECONDS
    assert str(job.trigger) == "cron[hour='7', minute='0']"


def test_ciclo_agendado_envia_resumos(monkeypatch: pytest.MonkeyPatch) -> None:
    result = PipelineResult(
        run=MagicMock(status=CollectionStatus.SUCCESS, tenders_new=3),
        matches=2,
        digest=DigestReport(emails_sent=1),
    )
    run_pipeline = MagicMock(return_value=result)
    monkeypatch.setattr(scheduler, "run_pipeline", run_pipeline)
    monkeypatch.setattr(scheduler, "get_sessionmaker", MagicMock())

    assert scheduler.scheduled_cycle(_settings()) is result
    kwargs = run_pipeline.call_args.kwargs
    assert kwargs == {"trigger": CollectionTrigger.SCHEDULED, "send_notifications": True}


def test_erro_no_ciclo_nao_derruba_o_agendador(monkeypatch: pytest.MonkeyPatch) -> None:
    # (outro teste reconfigura o logging da app; conferimos a chamada ao logger direto)
    logger = MagicMock()
    monkeypatch.setattr(scheduler, "logger", logger)
    monkeypatch.setattr(
        scheduler, "run_pipeline", MagicMock(side_effect=RuntimeError("banco fora"))
    )
    monkeypatch.setattr(scheduler, "get_sessionmaker", MagicMock())

    result = scheduler.scheduled_cycle(_settings())

    assert not result.ok
    logger.exception.assert_called_once_with("Falha no ciclo agendado")


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (PipelineResult(run=MagicMock(status=CollectionStatus.SUCCESS)), 0),
        (PipelineResult(skipped=True), 1),
    ],
)
def test_executar_agora(monkeypatch: pytest.MonkeyPatch, result: PipelineResult, code: int) -> None:
    monkeypatch.setattr(scheduler, "scheduled_cycle", MagicMock(return_value=result))

    assert scheduler.main(["--agora"]) == code


def test_main_inicia_o_agendador(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock()
    monkeypatch.setattr(scheduler, "build_scheduler", lambda settings: fake)
    monkeypatch.setattr(scheduler.signal, "signal", MagicMock())

    assert scheduler.main([]) == 0
    fake.start.assert_called_once()
