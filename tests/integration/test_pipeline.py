from collections.abc import Iterator
from datetime import UTC, date, datetime
from email.message import EmailMessage

import httpx
import pytest
import respx
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.collectors.pncp import PncpClient
from app.collectors.pncp.client import PUBLISHED_PATH, UPDATED_PATH
from app.config import Settings
from app.models import AlertMatch, CollectionRun, CollectionStatus, CollectionTrigger
from app.repositories import collection_runs
from app.services import pipeline
from app.services.locks import collection_lock, collection_running
from app.services.pipeline import run_pipeline
from tests.conftest import load_fixture
from tests.integration.factories import make_alert

BASE_URL = "https://pncp.test/api/consulta"
PAGE_1 = load_fixture("publicacao_mt_pregao_eletronico_p1.json")
PAGE_2 = load_fixture("publicacao_mt_pregao_eletronico_p2.json")


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="postgresql://x",
        pncp_base_url=BASE_URL,
        pncp_modalities="6",
        pncp_request_interval_seconds=0,
    )


def _client(settings: Settings) -> PncpClient:
    return PncpClient(BASE_URL, max_retries=1, sleep=lambda _: None)


@pytest.fixture
def sessions(migrated_engine: Engine, db_session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=migrated_engine, expire_on_commit=False)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(PUBLISHED_PATH, params={"pagina": "1"}).mock(
            return_value=httpx.Response(200, json=PAGE_1)
        )
        router.get(PUBLISHED_PATH, params={"pagina": "2"}).mock(
            return_value=httpx.Response(200, json=PAGE_2)
        )
        router.get(UPDATED_PATH).mock(return_value=httpx.Response(204))
        yield router


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


def _run(sessions: sessionmaker[Session], **kwargs: object) -> pipeline.PipelineResult:
    defaults: dict[str, object] = {
        "trigger": CollectionTrigger.SCHEDULED,
        "send_notifications": True,
        "date_from": date(2026, 11, 17),
        "date_to": date(2026, 11, 17),
        "client_factory": _client,
        # Relógio fixo: os prazos das respostas reais vencem e os alertas ignoram os vencidos.
        "clock": lambda: datetime(2026, 11, 22, 12, 0, tzinfo=UTC),
    }
    return run_pipeline(_settings(), sessions, **(defaults | kwargs))  # type: ignore[arg-type]


def test_trava_impede_duas_coletas_ao_mesmo_tempo(migrated_engine: Engine) -> None:
    with collection_lock(migrated_engine) as first:
        assert first
        assert collection_running(migrated_engine)
        with collection_lock(migrated_engine) as second:
            assert not second
    assert not collection_running(migrated_engine)  # solta ao sair


def test_ciclo_completo_coleta_cruza_e_envia(
    sessions: sessionmaker[Session],
    db_session: Session,
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = FakeSender()
    monkeypatch.setattr(pipeline.SmtpEmailSender, "from_settings", lambda settings: sender)
    make_alert(db_session, keywords=["aquisição"])  # o objeto de várias licitações reais
    db_session.commit()

    result = _run(sessions)

    assert result.ok
    assert result.run is not None and result.run.status == CollectionStatus.SUCCESS
    assert result.run.tenders_new > 0
    assert result.matches > 0
    assert result.digest is not None and result.digest.emails_sent == 1
    assert len(sender.sent) == 1
    sent = db_session.scalars(select(AlertMatch.notified_at)).all()
    assert sent and all(sent)


def test_coletar_agora_nao_envia_resumos(
    sessions: sessionmaker[Session], db_session: Session, api: respx.MockRouter
) -> None:
    make_alert(db_session, keywords=["aquisição"])
    db_session.commit()

    result = _run(sessions, trigger=CollectionTrigger.MANUAL, send_notifications=False)

    assert result.ok and result.digest is None
    assert result.matches > 0
    assert all(m is None for m in db_session.scalars(select(AlertMatch.notified_at)))


def test_pula_se_outra_coleta_estiver_rodando(
    sessions: sessionmaker[Session], migrated_engine: Engine, db_session: Session
) -> None:
    with collection_lock(migrated_engine):
        result = _run(sessions)

    assert result.skipped and not result.ok
    assert db_session.scalars(select(CollectionRun)).all() == []


def test_coleta_interrompida_e_marcada_como_falha(
    sessions: sessionmaker[Session], db_session: Session, api: respx.MockRouter
) -> None:
    stale = collection_runs.start_run(
        db_session,
        trigger=CollectionTrigger.SCHEDULED,
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 1),
    )
    db_session.commit()

    _run(sessions, send_notifications=False)

    db_session.refresh(stale)
    assert stale.status == CollectionStatus.FAILED
    assert "interrompida" in (stale.error_message or "")
    assert stale.finished_at is not None
    assert collection_runs.recent_runs(db_session)[0].status == CollectionStatus.SUCCESS


def test_falha_da_api_fica_registrada(sessions: sessionmaker[Session], db_session: Session) -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(PUBLISHED_PATH).mock(return_value=httpx.Response(400, text="erro"))
        result = _run(sessions, send_notifications=False)

    assert not result.ok
    assert result.run is not None and result.run.status == CollectionStatus.FAILED


def test_agendador_avisa_o_administrador_depois_de_falhas_seguidas(
    sessions: sessionmaker[Session], db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = FakeSender()
    monkeypatch.setattr(pipeline.SmtpEmailSender, "from_settings", lambda settings: sender)
    settings = _settings().model_copy(update={"admin_alert_email": "admin@exemplo.com.br"})

    with respx.mock(base_url=BASE_URL) as router:
        router.get(PUBLISHED_PATH).mock(return_value=httpx.Response(400, text="erro"))
        for _ in range(2):
            run_pipeline(
                settings, sessions, trigger=CollectionTrigger.SCHEDULED, send_notifications=True,
                date_from=date(2026, 11, 17), date_to=date(2026, 11, 17), client_factory=_client,
            )  # fmt: skip

    assert [m["To"] for m in sender.sent] == ["admin@exemplo.com.br"]
    runs = collection_runs.recent_scheduled_runs(db_session, 5)
    assert [r.notification_failures for r in runs] == [0, 0]  # sem alertas: nada a enviar
