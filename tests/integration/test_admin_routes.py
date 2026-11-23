from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import admin
from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Alert, AlertMatch, CollectionStatus, CollectionTrigger
from app.repositories import collection_runs
from app.security import COOKIE_NAME
from app.services.locks import collection_lock
from app.services.pipeline import PipelineResult
from tests.integration.factories import make_alert, make_tender

PASSWORD = "senha-do-admin"
FORM = {
    "name": "TI em Rondonópolis",
    "email": "ti@empresa.com",
    "keywords": "computador\nimpressora",
    "municipalities": "Rondonópolis\nPedra Preta",
    "min_value": "",
    "max_value": "500000",
    "telegram_chat_id": "",
    "active": "on",
}


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://x",
        "admin_password": PASSWORD,
        "secret_key": "chave-de-teste",
        "pncp_states": "MT",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _client(db_session: Session, settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, follow_redirects=False)


@pytest.fixture(autouse=True)
def _no_login_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin, "LOGIN_FAILURE_DELAY_SECONDS", 0)


@pytest.fixture
def anonymous(db_session: Session) -> Iterator[TestClient]:
    with _client(db_session, _settings()) as client:
        yield client


@pytest.fixture
def logged(anonymous: TestClient) -> TestClient:
    response = anonymous.post("/admin/login", data={"password": PASSWORD, "next": ""})
    assert response.status_code == 303
    return anonymous


# --- Login e proteção ------------------------------------------------------------------


def test_sem_senha_configurada_a_area_fica_desativada(db_session: Session) -> None:
    with _client(db_session, _settings(admin_password="")) as client:
        for response in (client.get("/admin/alertas"), client.get("/admin/login")):
            assert response.status_code == 503
            assert "ADMIN_PASSWORD" in response.text


def test_paginas_exigem_login(anonymous: TestClient) -> None:
    response = anonymous.get("/admin/alertas/novo")

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login?next=%2Fadmin%2Falertas%2Fnovo"
    assert anonymous.post("/admin/alertas/novo", data=FORM).status_code == 303


def test_senha_errada(anonymous: TestClient) -> None:
    response = anonymous.post("/admin/login", data={"password": "chute"})

    assert response.status_code == 401
    assert "Senha incorreta" in response.text
    assert COOKIE_NAME not in response.cookies


def test_login_cria_cookie_seguro_e_volta_para_a_pagina(anonymous: TestClient) -> None:
    response = anonymous.post(
        "/admin/login", data={"password": PASSWORD, "next": "/admin/alertas/novo"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/alertas/novo"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/admin" in cookie
    assert anonymous.get("/admin/alertas").status_code == 200


@pytest.mark.parametrize("target", ["https://site-malicioso.com", "//evil.com", "/licitacoes/1"])
def test_login_nao_redireciona_para_fora_do_admin(anonymous: TestClient, target: str) -> None:
    response = anonymous.post("/admin/login", data={"password": PASSWORD, "next": target})

    assert response.headers["location"] == "/admin/alertas"


@pytest.mark.parametrize(
    ("base_url", "secure"),
    [("https://radar.exemplo.com.br", True), ("http://192.168.0.10:8000", False)],
)
def test_cookie_secure_quando_o_endereco_e_https(
    db_session: Session, base_url: str, secure: bool
) -> None:
    settings = _settings(app_env="production", app_base_url=base_url)
    with _client(db_session, settings) as client:
        response = client.post(
            "/admin/login", data={"password": PASSWORD}, headers={"Origin": base_url}
        )

    assert ("Secure" in response.headers["set-cookie"]) is secure


def test_post_de_outro_site_e_bloqueado(logged: TestClient, db_session: Session) -> None:
    response = logged.post(
        "/admin/alertas/novo", data=FORM, headers={"Origin": "https://site-malicioso.com"}
    )

    assert response.status_code == 403
    assert db_session.scalars(select(Alert)).all() == []
    ok = logged.post("/admin/alertas/novo", data=FORM, headers={"Origin": "http://testserver"})
    assert ok.status_code == 303


def test_sair(logged: TestClient) -> None:
    response = logged.post("/admin/logout")

    assert response.status_code == 303
    assert 'radar_admin=""' in response.headers["set-cookie"]


# --- Alertas ---------------------------------------------------------------------------


def test_cria_alerta_pelo_formulario(logged: TestClient, db_session: Session) -> None:
    make_tender(
        db_session,
        object_description="Aquisição de computadores",
        proposals_close_at=datetime.now(UTC) + timedelta(days=3),
    )
    db_session.commit()

    response = logged.post("/admin/alertas/novo", data=FORM)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/alertas?msg=created&matched=1"
    alert = db_session.scalars(select(Alert)).one()
    assert alert.keywords == ["computador", "impressora"]
    assert alert.municipalities == ["5107602", "5106372"]  # Pedra Preta de MT, não de RN
    assert alert.max_value == 500000
    assert alert.active

    page = logged.get(response.headers["location"])
    assert "1 licitação(ões) com propostas abertas já casam" in page.text
    assert "TI em Rondonópolis" in page.text
    assert "Rondonópolis/MT, Pedra Preta/MT" in page.text


def test_formulario_invalido_mostra_erros_e_mantem_valores(
    logged: TestClient, db_session: Session
) -> None:
    data = {**FORM, "email": "sem-arroba", "municipalities": "Rondonopolys", "keywords": "de"}

    response = logged.post("/admin/alertas/novo", data=data)

    assert response.status_code == 422
    assert "e-mail inválido" in response.text
    assert "município não encontrado" in response.text
    assert 'value="TI em Rondonópolis"' in response.text  # o que foi digitado continua lá
    assert db_session.scalars(select(Alert)).all() == []

    response = logged.post("/admin/alertas/novo", data={**FORM, "keywords": "de\npara"})
    assert response.status_code == 422
    assert "sem efeito na busca" in response.text


def test_edita_ativa_desativa_e_exclui(logged: TestClient, db_session: Session) -> None:
    alert = make_alert(db_session, name="Antigo", keywords=["pneu"])
    db_session.commit()

    page = logged.get(f"/admin/alertas/{alert.id}/editar")
    assert page.status_code == 200
    assert ">pneu</textarea>" in page.text

    response = logged.post(f"/admin/alertas/{alert.id}/editar", data={**FORM, "name": "Novo"})
    assert response.status_code == 303
    db_session.refresh(alert)
    assert alert.name == "Novo"

    logged.post(f"/admin/alertas/{alert.id}/ativo", data={"active": "0"})
    db_session.refresh(alert)
    assert not alert.active

    logged.post(f"/admin/alertas/{alert.id}/ativo", data={"active": "1"})
    db_session.refresh(alert)
    assert alert.active

    assert logged.get(f"/admin/alertas/{alert.id}").status_code == 200
    logged.post(f"/admin/alertas/{alert.id}/excluir")
    assert db_session.scalars(select(Alert)).all() == []
    assert logged.get(f"/admin/alertas/{alert.id}/editar").status_code == 404


def test_nome_do_alerta_nao_quebra_o_javascript_de_confirmacao(
    logged: TestClient, db_session: Session
) -> None:
    make_alert(db_session, name="O'Brien\"); alert('x')")
    db_session.commit()

    html = logged.get("/admin/alertas").text

    assert "alert('x')" not in html
    assert "\\u0027" in html  # aspas simples escapadas dentro do JSON


def test_enviar_resumos_agora(
    logged: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[EmailMessage] = []

    class Sender:
        def send(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(admin.SmtpEmailSender, "from_settings", lambda settings: Sender())
    alert = make_alert(db_session, keywords=["computador"])
    tender = make_tender(db_session, object_description="Computadores")
    db_session.add(AlertMatch(alert_id=alert.id, tender_id=tender.id))
    db_session.commit()

    response = logged.post("/admin/resumos/enviar")

    assert response.status_code == 303
    assert "msg=digest&emails=1" in response.headers["location"]
    assert len(sent) == 1
    page = logged.get(response.headers["location"])
    assert "Resumos enviados: 1 e-mail(s)" in page.text


def test_lista_avisa_quando_smtp_nao_esta_configurado(logged: TestClient) -> None:
    assert "SMTP não configurado" in logged.get("/admin/alertas").text


# --- Coletas ---------------------------------------------------------------------------


def test_tela_de_coletas(logged: TestClient, db_session: Session) -> None:
    run = collection_runs.start_run(
        db_session,
        trigger=CollectionTrigger.SCHEDULED,
        date_from=date(2026, 11, 21),
        date_to=date(2026, 11, 22),
        states=["MT"],
    )
    collection_runs.finish_run(run, CollectionStatus.FAILED, "PNCP respondeu 500")
    db_session.commit()

    html = logged.get("/admin/coletas").text

    assert "Falhou" in html and "PNCP respondeu 500" in html
    assert "21/11/2026 a 22/11/2026" in html
    assert "Coleta automática às 7h e 18h (America/Cuiaba)" in html
    assert "Próxima:" in html


def test_coletar_agora_roda_em_segundo_plano(
    logged: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_pipeline(settings: object, sessions: object, **kwargs: object) -> PipelineResult:
        calls.append(kwargs)
        return PipelineResult()

    monkeypatch.setattr(admin, "run_pipeline", fake_pipeline)

    response = logged.post("/admin/coletas/agora")

    assert response.headers["location"] == "/admin/coletas?msg=collect_started"
    assert calls == [{"trigger": CollectionTrigger.MANUAL, "send_notifications": False}]
    assert "Coleta iniciada" in logged.get(response.headers["location"]).text


def test_coletar_agora_com_coleta_em_andamento(
    logged: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_pipeline = MagicMock()
    monkeypatch.setattr(admin, "run_pipeline", run_pipeline)

    with collection_lock(db_session.get_bind()):
        response = logged.post("/admin/coletas/agora")
        page = logged.get("/admin/coletas").text

    assert response.headers["location"] == "/admin/coletas?msg=collect_busy"
    run_pipeline.assert_not_called()
    assert "Há uma coleta em andamento" in page
    assert "disabled" in page
