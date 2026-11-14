from datetime import datetime
from email.message import EmailMessage
import logging
import smtplib

from .config import settings

logger = logging.getLogger(__name__)


def smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.smtp_from_email)


def send_password_reset_email(recipient: str, reset_url: str) -> None:
    if not smtp_is_configured():
        logger.warning("SMTP not configured. Cannot send password reset to %s", recipient)
        return
    try:
        message = EmailMessage()
        message["Subject"] = "Reset your TrimTime password"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient

        plain_text = f"""Hello,

Use this secure link to reset your TrimTime password. The link expires in 30 minutes:

{reset_url}

If you did not request this, please ignore this email.

Best regards,
TrimTime Team
"""
        html_text = f"""<!doctype html>
<html>
<head><meta charset="utf-8" /></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;background:#0f172a;color:#f8fafc;padding:30px;margin:0;">
  <div style="max-width:480px;margin:0 auto;background:#1e293b;border-radius:16px;border:1px solid #334155;padding:32px;text-align:center;">
    <div style="font-size:22px;font-weight:800;color:#38bdf8;letter-spacing:-0.5px;margin-bottom:20px;">TRIM<span style="color:#ffffff;">TIME</span></div>
    <h2 style="font-size:20px;color:#ffffff;margin:0 0 12px;">Reset Your Password</h2>
    <p style="font-size:14px;color:#94a3b8;line-height:1.6;margin:0 0 24px;">Click the button below to choose a new password for your TrimTime account. This link expires in 30 minutes.</p>
    <a href="{reset_url}" style="display:inline-block;padding:12px 28px;background:#38bdf8;color:#0f172a;text-decoration:none;font-weight:700;border-radius:10px;font-size:15px;">Reset Password</a>
    <p style="font-size:12px;color:#64748b;margin:28px 0 0;">If you did not request this reset, you can safely ignore this email.</p>
  </div>
</body>
</html>"""
        message.set_content(plain_text)
        message.add_alternative(html_text, subtype="html")

        if settings.smtp_port == 465:
            server_class = smtplib.SMTP_SSL
        else:
            server_class = smtplib.SMTP

        with server_class(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_port != 465 and settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
            logger.info("Password reset email sent successfully to %s", recipient)
    except Exception as exc:
        logger.warning("Failed to send password reset email to %s: %s", recipient, exc)


def send_customer_otp_email(recipient: str, otp: str) -> None:
    if not smtp_is_configured():
        logger.warning("SMTP is not configured. Cannot send OTP to %s", recipient)
        return
    try:
        current_year = datetime.now().year
        message = EmailMessage()
        message["Subject"] = f"Your TrimTime Verification Code is {otp}"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient

        plain_text = f"""Hello,

Your TrimTime verification code is: {otp}

This code is valid for 10 minutes. Please enter it in the app to continue.

If you did not request this code, please ignore this email.

Best regards,
TrimTime Team
"""
        html_text = f"""<!doctype html>
<html>
<head><meta charset="utf-8" /></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;background-color:#0f172a;margin:0;padding:32px 16px;color:#f8fafc;">
  <div style="max-width:480px;margin:0 auto;background:#1e293b;border-radius:16px;border:1px solid #334155;overflow:hidden;box-shadow:0 12px 30px rgba(0,0,0,0.3);">
    <div style="background:#090d16;padding:24px;text-align:center;border-bottom:1px solid #334155;">
      <span style="font-size:24px;font-weight:900;letter-spacing:-0.5px;color:#38bdf8;">TRIM<span style="color:#ffffff;">TIME</span></span>
    </div>
    <div style="padding:32px 24px;text-align:center;">
      <h1 style="font-size:20px;font-weight:700;margin:0 0 10px;color:#ffffff;">Verify Your Email</h1>
      <p style="font-size:14px;color:#94a3b8;line-height:1.6;margin:0 0 24px;">Use the 6-digit verification code below to sign in or complete your registration. Do not share this code with anyone.</p>
      <div style="background:#090d16;border:2px dashed #38bdf8;border-radius:12px;padding:16px 24px;display:inline-block;margin-bottom:20px;">
        <span style="font-size:36px;font-weight:800;letter-spacing:8px;color:#38bdf8;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;">{otp}</span>
      </div>
      <p style="font-size:12px;color:#cbd5e1;margin:0 0 8px;">⏱️ This code expires in <strong>10 minutes</strong>.</p>
      <p style="font-size:12px;color:#64748b;margin:16px 0 0;">If you didn't request this code, you can safely ignore this email.</p>
    </div>
    <div style="background:#090d16;padding:16px 24px;text-align:center;border-top:1px solid #334155;font-size:11px;color:#64748b;">
      © {current_year} TrimTime · Skip the waiting room. Keep every chair moving.
    </div>
  </div>
</body>
</html>"""
        message.set_content(plain_text)
        message.add_alternative(html_text, subtype="html")

        if settings.smtp_port == 465:
            server_class = smtplib.SMTP_SSL
        else:
            server_class = smtplib.SMTP

        with server_class(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_port != 465 and settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
            logger.info("Customer OTP email sent successfully to %s", recipient)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "SMTP Authentication Failed for %s. Google accounts require a 16-character App Password! "
            "Go to https://myaccount.google.com/apppasswords to create one. Details: %s",
            settings.smtp_username, exc
        )
    except Exception as exc:
        logger.error("Failed to send customer OTP email to %s: %s", recipient, exc)

