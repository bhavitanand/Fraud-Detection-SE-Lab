"""One-time-code delivery. 'console' prints to the server terminal (development only); 'smtp' sends real e-mail."""
from __future__ import annotations

import logging
import smtplib
import sys
from email.message import EmailMessage

from app.core.config import Settings
from app.core.errors import AppError

log = logging.getLogger("fraud.mail")


class DeliveryFailed(AppError):
    status, code = 503, "delivery_failed"


def send_otp(settings: Settings, to: str, code: str, minutes: int) -> None:
    subject, body = "Your Fraud Desk sign-in code", f"Your sign-in code is {code}. It expires in {minutes} minutes. If you did not try to sign in, ignore this message."
    if settings.otp_delivery == "smtp":
        if not (settings.smtp_host and settings.smtp_from):
            raise DeliveryFailed("E-mail delivery is not configured on the server.")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password or "")
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            log.error("OTP e-mail failed: %s", type(exc).__name__)
            raise DeliveryFailed("Could not send the sign-in code. Try again.") from exc
        return
    # Development convenience: the code is visible to whoever runs the server. Never use in a shared deployment.
    print(f"\n[DEV ONLY] sign-in code for {to}: {code}\n", file=sys.stderr, flush=True)
