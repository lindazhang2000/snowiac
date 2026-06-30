"""Email notifier. Closure sink for email-sourced requests.

Mirrors :mod:`servicenow` (real client + mock + ``build_*`` factory). When
SMTP is not configured (or NOTIFY_EMAIL_ENABLED is false) a no-op mock is
returned that just logs, so the workflow runs unchanged in local/dev.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from ..config import get_settings

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpNotifier:
    """Sends mail over SMTP. smtplib is blocking, so calls run in a thread."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        use_tls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender = sender
        self._use_tls = use_tls

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=30) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password)
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        if not to:
            log.warning("No recipient address — skipping email notification")
            return
        await asyncio.to_thread(self._send_sync, to, subject, body)
        log.info("Sent email to %s: %s", to, subject)


class MockNotifier:
    """No-op notifier used when SMTP is not configured. Just logs."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        log.info("[MOCK EMAIL] to=%s subject=%s\n%s", to, subject, body)
        self.sent.append((to, subject, body))


def build_notifier() -> Notifier:
    s = get_settings()
    if not s.notify_email_enabled or not s.smtp_host:
        return MockNotifier()
    return SmtpNotifier(
        s.smtp_host,
        s.smtp_port,
        s.smtp_user,
        s.smtp_password,
        s.smtp_from,
        s.smtp_use_tls,
    )
