from datetime import datetime, timezone
from email.message import EmailMessage
import logging
import smtplib
import ssl
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

# In-memory record of the most recent SMTP dispatch attempt for live diagnostics
_last_smtp_status: dict[str, Any] = {
    "timestamp": None,
    "success": None,
    "recipient": None,
    "strategy": None,
    "error": None,
}


def get_last_smtp_status() -> dict[str, Any]:
    return dict(_last_smtp_status)


def smtp_is_configured() -> bool:
    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_username or "").strip()
    pwd = (settings.smtp_password or "").strip()
    return bool(host and user and pwd)


def _clean_credentials() -> tuple[str, int, str, str, str]:
    host = settings.smtp_host.strip().strip('"').strip("'")
    port = settings.smtp_port or 465
    user = settings.smtp_username.strip().strip('"').strip("'")
    pwd = settings.smtp_password.strip().strip('"').strip("'")
    from_email = (settings.smtp_from_email or user).strip().strip('"').strip("'")
    return host, port, user, pwd, from_email


def _dispatch_smtp(message: EmailMessage, recipient: str, context_desc: str = "Email") -> tuple[bool, str]:
    """
    Robust multi-strategy SMTP sender.
    Attempts delivery on the primary configured port (e.g. 465 SSL or 587 STARTTLS).
    If network timeout or connection fails (common on cloud servers like Render that block port 587),
    automatically falls back to port 465 SSL (or 587 STARTTLS).
    Also handles 16-character Google App Passwords with or without spaces.
    """
    global _last_smtp_status

    if not smtp_is_configured():
        msg = f"SMTP is not configured on this server. Cannot dispatch {context_desc} to {recipient}."
        logger.warning(msg)
        _last_smtp_status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "recipient": recipient,
            "strategy": "None",
            "error": "SMTP not configured (missing host, username, or password)",
        }
        return False, msg

    host, primary_port, user, pwd, from_email = _clean_credentials()

    # Build strategies: primary port first, then fallback port
    # Port 465 SSL is direct TLS from byte 0 (never blocked on cloud platforms)
    # Port 587 STARTTLS starts unencrypted then upgrades (sometimes filtered by cloud firewalls)
    strategies: list[dict[str, Any]] = []
    
    if primary_port == 465:
        strategies.append({"port": 465, "ssl": True, "name": "Port 465 (Direct SSL)"})
        strategies.append({"port": 587, "ssl": False, "name": "Port 587 (STARTTLS fallback)"})
    else:
        strategies.append({"port": primary_port, "ssl": False, "name": f"Port {primary_port} (STARTTLS)"})
        strategies.append({"port": 465, "ssl": True, "name": "Port 465 (Direct SSL fallback)"})

    # Prepare password variants (with spaces vs without spaces)
    passwords = [pwd]
    if " " in pwd:
        passwords.append(pwd.replace(" ", ""))
    elif len(pwd) == 16:
        # 16-char Google App Password without spaces -> also try grouped by 4
        passwords.append(f"{pwd[0:4]} {pwd[4:8]} {pwd[8:12]} {pwd[12:16]}")

    errors: list[str] = []

    for strat in strategies:
        port = strat["port"]
        use_ssl = strat["ssl"]
        strat_name = strat["name"]
        
        try:
            logger.info("Attempting %s to %s via %s:%s...", context_desc, recipient, host, port)
            ctx = ssl.create_default_context()

            if use_ssl:
                server = smtplib.SMTP_SSL(host, port, timeout=12, context=ctx)
            else:
                server = smtplib.SMTP(host, port, timeout=12)
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls(context=ctx)
                    server.ehlo()

            with server:
                # Attempt login with password variants if needed
                logged_in = False
                last_auth_err = None

                for pass_attempt in passwords:
                    try:
                        server.login(user, pass_attempt)
                        logged_in = True
                        break
                    except smtplib.SMTPAuthenticationError as auth_err:
                        last_auth_err = auth_err
                        logger.warning("SMTP auth failed with password variant on %s: %s", strat_name, auth_err)

                if not logged_in:
                    raise last_auth_err or smtplib.SMTPAuthenticationError(535, b"Authentication failed")

                server.send_message(message)
                logger.info("SUCCESS: %s delivered to %s via %s", context_desc, recipient, strat_name)

                _last_smtp_status = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "success": True,
                    "recipient": recipient,
                    "strategy": strat_name,
                    "error": None,
                }
                return True, f"Delivered via {strat_name}"

        except Exception as exc:
            err_msg = f"{strat_name} failed: {type(exc).__name__} ({exc})"
            logger.warning(err_msg)
            errors.append(err_msg)

    final_error = " | ".join(errors)
    logger.error("All SMTP strategies exhausted for %s to %s: %s", context_desc, recipient, final_error)
    _last_smtp_status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "recipient": recipient,
        "strategy": "Exhausted all",
        "error": final_error,
    }
    return False, final_error


def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    if not smtp_is_configured():
        logger.warning("SMTP not configured. Cannot send password reset to %s", recipient)
        return False

    try:
        _, _, _, _, from_email = _clean_credentials()
        message = EmailMessage()
        message["Subject"] = "Reset your TrimTime password"
        message["From"] = f"TrimTime <{from_email}>"
        message["Sender"] = from_email
        message["Reply-To"] = from_email
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

        ok, _ = _dispatch_smtp(message, recipient, "Password Reset")
        return ok
    except Exception as exc:
        logger.error("Failed to build password reset email for %s: %s", recipient, exc)
        return False


def send_customer_otp_email(recipient: str, otp: str) -> bool:
    if not smtp_is_configured():
        logger.warning("SMTP is not configured on this server. Cannot send OTP to %s", recipient)
        return False

    try:
        current_year = datetime.now().year
        _, _, _, _, from_email = _clean_credentials()

        message = EmailMessage()
        message["Subject"] = f"Your TrimTime Verification Code is {otp}"
        message["From"] = f"TrimTime <{from_email}>"
        message["Sender"] = from_email
        message["Reply-To"] = from_email
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

        ok, _ = _dispatch_smtp(message, recipient, "Customer OTP")
        return ok
    except Exception as exc:
        logger.error("Failed to build customer OTP email for %s: %s", recipient, exc)
        return False


def test_smtp_connection(test_recipient: str | None = None) -> dict[str, Any]:
    """
    Diagnostic helper to test SMTP settings on the server.
    """
    configured = smtp_is_configured()
    if not configured:
        return {
            "configured": False,
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "username": settings.smtp_username,
            "from_email": settings.smtp_from_email,
            "error": "Missing SMTP_HOST, SMTP_USERNAME, or SMTP_PASSWORD in server environment variables.",
            "instructions": "Set SMTP_HOST=smtp.gmail.com, SMTP_PORT=465, SMTP_USERNAME=your_email, SMTP_PASSWORD=your_app_password in your server environment settings."
        }

    host, primary_port, user, pwd, from_email = _clean_credentials()
    results: dict[str, Any] = {
        "configured": True,
        "host": host,
        "primary_port": primary_port,
        "username": user,
        "from_email": from_email,
        "port_465_ssl": None,
        "port_587_starttls": None,
        "test_email_sent": False,
        "last_status": get_last_smtp_status(),
    }

    ctx = ssl.create_default_context()

    # Test Port 465 SSL
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=8, context=ctx) as s:
            s.login(user, pwd if " " not in pwd else pwd.replace(" ", ""))
            results["port_465_ssl"] = "SUCCESS (Connected & Authenticated)"
    except Exception as exc:
        results["port_465_ssl"] = f"FAILED: {type(exc).__name__} ({exc})"

    # Test Port 587 STARTTLS
    try:
        with smtplib.SMTP(host, 587, timeout=8) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(user, pwd if " " not in pwd else pwd.replace(" ", ""))
            results["port_587_starttls"] = "SUCCESS (Connected & Authenticated)"
    except Exception as exc:
        results["port_587_starttls"] = f"FAILED: {type(exc).__name__} ({exc})"

    # Optional test email dispatch
    if test_recipient:
        msg = EmailMessage()
        msg["Subject"] = "TrimTime SMTP Verification Test"
        msg["From"] = f"TrimTime <{from_email}>"
        msg["Sender"] = from_email
        msg["Reply-To"] = from_email
        msg["To"] = test_recipient
        msg.set_content("Congratulations! Your TrimTime server SMTP configuration is operating successfully and ready to deliver OTPs.")
        ok, detail = _dispatch_smtp(msg, test_recipient, "Test Verification Email")
        results["test_email_sent"] = ok
        results["test_email_detail"] = detail

    return results
