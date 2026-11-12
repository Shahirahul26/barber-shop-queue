from email.message import EmailMessage
import logging
import smtplib

from .config import settings

logger = logging.getLogger(__name__)


def smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.smtp_from_email)


def send_password_reset_email(recipient: str, reset_url: str) -> None:
    if not smtp_is_configured():
        return
    try:
        message = EmailMessage()
        message["Subject"] = "Reset your TrimTime password"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(f"Use this secure link to reset your TrimTime password. The link expires in 30 minutes:\n\n{reset_url}\n\nIf you did not request this, ignore this email.")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        logger.warning("Failed to send password reset email to %s: %s", recipient, exc)


def send_customer_otp_email(recipient: str, otp: str) -> None:
    if not smtp_is_configured():
        return
    try:
        message = EmailMessage()
        message["Subject"] = "Your TrimTime verification code"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(f"Your TrimTime verification code is {otp}. It expires in 10 minutes.")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        logger.warning("Failed to send customer OTP email to %s: %s", recipient, exc)
