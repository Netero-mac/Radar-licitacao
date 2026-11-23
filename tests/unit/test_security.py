from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.security import check_password, issue_token, verify_token

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://x",
        "admin_password": "senha-forte",
        "secret_key": "chave-secreta",
        "admin_session_hours": 12,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_senha() -> None:
    settings = _settings()

    assert check_password(settings, "senha-forte")
    assert not check_password(settings, "senha-fraca")
    assert not check_password(settings, "")


def test_token_valido_ate_expirar() -> None:
    settings = _settings()
    token = issue_token(settings, now=NOW)

    assert verify_token(settings, token, now=NOW + timedelta(hours=11))
    assert not verify_token(settings, token, now=NOW + timedelta(hours=13))


def test_token_adulterado_e_rejeitado() -> None:
    settings = _settings()
    expires, _, signature = issue_token(settings, now=NOW).partition(".")
    later = str(int(expires) + 86_400)

    assert not verify_token(settings, f"{later}.{signature}", now=NOW)  # estende a validade
    assert not verify_token(settings, f"{expires}.{'0' * 64}", now=NOW)
    for garbage in ["", "abc", "123.", ".abc", None]:
        assert not verify_token(settings, garbage, now=NOW)


def test_trocar_senha_ou_chave_derruba_as_sessoes() -> None:
    token = issue_token(_settings(), now=NOW)

    assert not verify_token(_settings(admin_password="outra-senha"), token, now=NOW)
    assert not verify_token(_settings(secret_key="outra-chave"), token, now=NOW)


def test_sem_configuracao_o_admin_fica_desativado() -> None:
    for settings in (_settings(admin_password=""), _settings(secret_key=None)):
        assert not settings.admin_enabled
        assert not check_password(settings, "senha-forte")
        assert not verify_token(settings, "123.abc")
