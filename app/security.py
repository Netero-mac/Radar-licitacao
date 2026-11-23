"""Login da área administrativa: senha única (ADMIN_PASSWORD) e cookie assinado.

O cookie guarda só a validade e uma assinatura HMAC-SHA256 feita com SECRET_KEY. A
assinatura inclui uma impressão digital da senha: trocar ADMIN_PASSWORD (ou SECRET_KEY)
desconecta todas as sessões abertas.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from app.config import Settings

COOKIE_NAME = "radar_admin"


def _keys(settings: Settings) -> tuple[bytes, bytes]:
    assert settings.admin_password is not None and settings.secret_key is not None
    secret = settings.secret_key.get_secret_value().encode()
    password_fingerprint = hashlib.sha256(
        settings.admin_password.get_secret_value().encode()
    ).digest()
    return secret, password_fingerprint


def _signature(settings: Settings, expires: int) -> str:
    secret, fingerprint = _keys(settings)
    payload = b"admin:" + str(expires).encode() + b":" + fingerprint
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def check_password(settings: Settings, password: str) -> bool:
    if not settings.admin_enabled:
        return False
    assert settings.admin_password is not None
    expected = settings.admin_password.get_secret_value().encode()
    return hmac.compare_digest(password.encode(), expected)


def issue_token(settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    expires = int((now + timedelta(hours=settings.admin_session_hours)).timestamp())
    return f"{expires}.{_signature(settings, expires)}"


def verify_token(settings: Settings, token: str | None, now: datetime | None = None) -> bool:
    if not token or not settings.admin_enabled:
        return False
    expires_text, _, signature = token.partition(".")
    if not expires_text.isdigit() or not signature:
        return False
    expires = int(expires_text)
    if expires < (now or datetime.now(UTC)).timestamp():
        return False
    return hmac.compare_digest(signature, _signature(settings, expires))
