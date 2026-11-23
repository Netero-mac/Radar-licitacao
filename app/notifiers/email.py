"""Envio de e-mail por SMTP (biblioteca padrão: smtplib + email.message)."""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from app.config import Settings


class EmailError(Exception):
    pass


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


def build_message(*, sender: str, to: str, subject: str, text: str, html: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="radar-licitacoes")
    # Evita respostas automáticas (férias etc.) voltando para o remetente.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


class SmtpEmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        security: str = "starttls",
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.security = security
        self.username = username
        self.password = password
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpEmailSender | None":
        """None quando o SMTP não está configurado (envio de e-mail desativado)."""
        if not settings.smtp_host:
            return None
        return cls(
            settings.smtp_host,
            settings.smtp_port,
            security=settings.smtp_security,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            timeout=settings.smtp_timeout_seconds,
        )

    def _connect(self) -> smtplib.SMTP:
        if self.security == "ssl":
            return smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=ssl.create_default_context()
            )
        smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        if self.security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        return smtp

    def send(self, message: EmailMessage) -> None:
        try:
            with self._connect() as smtp:
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"falha ao enviar e-mail via {self.host}:{self.port}: {exc}") from exc
