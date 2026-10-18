"""Envío de correo por SMTP (reporte cada 3 días y avisos del vigilante).

Configuración en ``.env`` (nunca en el repo ni en logs):

    REPORT_EMAIL_TO=nahimsalta@gmail.com
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=cuenta-que-envia@gmail.com
    SMTP_PASSWORD=contraseña-de-aplicación-de-16-letras
    REPORT_EMAIL_FROM=            # opcional; por defecto SMTP_USER

Con Gmail hace falta una "contraseña de aplicación" (Cuenta de Google →
Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones).
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from utils.logging_setup import setup_logger
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus

logger = setup_logger("mailer", "reports.log")


def configured() -> bool:
    return all(os.getenv(name, "").strip() for name in ("REPORT_EMAIL_TO", "SMTP_USER", "SMTP_PASSWORD"))


def send_email(subject: str, html: str, text: str) -> OperationResult:
    if not configured():
        return OperationResult(StageStatus.BLOCKED, error_type="smtp_not_configured")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
    sender = os.getenv("REPORT_EMAIL_FROM", "").strip() or user
    recipients = [r.strip() for r in os.getenv("REPORT_EMAIL_TO", "").split(",") if r.strip()]

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("La Voz Riojana · Sistema", sender))
    message["To"] = ", ".join(recipients)
    message["Message-ID"] = make_msgid(domain="lavozriojana.com")
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls(context=context)
                smtp.login(user, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP rechazó el usuario o la contraseña (revisar SMTP_USER/SMTP_PASSWORD)")
        return OperationResult(StageStatus.FAILED, error_type="smtp_auth_failed")
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("No se pudo enviar el correo: %s", type(exc).__name__)
        return OperationResult(StageStatus.DEGRADED, error_type="smtp_error", error_code=type(exc).__name__, retryable=True)
    logger.info("Correo enviado a %s destinatario(s): %s", len(recipients), subject)
    return OperationResult(StageStatus.SUCCESS)
