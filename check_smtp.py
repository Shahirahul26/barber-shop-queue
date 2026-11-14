"""
TrimTime SMTP Email Diagnostic Script
Run this script to test if your Gmail / SMTP configuration can successfully send emails:
    python test_smtp.py
"""
import smtplib
from email.message import EmailMessage
from app.config import settings

def test_smtp():
    print("=" * 60)
    print("TrimTime SMTP Diagnostic Test")
    print("=" * 60)
    print(f"Host:     {settings.smtp_host}")
    print(f"Port:     {settings.smtp_port}")
    print(f"User:     {settings.smtp_username}")
    print(f"Password: {'*' * (len(settings.smtp_password) - 3) + settings.smtp_password[-3:] if len(settings.smtp_password) >= 3 else '***'}")
    print(f"From:     {settings.smtp_from_email}")
    print(f"Use TLS:  {settings.smtp_use_tls}")
    print("-" * 60)

    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        print("FAIL: SMTP settings are incomplete in your .env file.")
        print("Please configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL.")
        return False

    server_class = smtplib.SMTP_SSL if settings.smtp_port == 465 else smtplib.SMTP

    try:
        print("Connecting to SMTP server...")
        with server_class(settings.smtp_host, settings.smtp_port, timeout=12) as server:
            if settings.smtp_port != 465 and settings.smtp_use_tls:
                print("Initiating STARTTLS encryption...")
                server.starttls()
            print("Authenticating...")
            server.login(settings.smtp_username, settings.smtp_password)
            print("Authentication SUCCESSFUL!")

            print(f"Sending test verification email to {settings.smtp_username}...")
            msg = EmailMessage()
            msg["Subject"] = "Test OTP: TrimTime Email System Working!"
            msg["From"] = settings.smtp_from_email
            msg["To"] = settings.smtp_username
            msg.set_content("Congratulations! Your TrimTime SMTP email integration is configured correctly and ready to deliver customer OTPs.")
            server.send_message(msg)
            print(f"SUCCESS: Test email successfully delivered to {settings.smtp_username}!")
            print("=" * 60)
            return True

    except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected) as exc:
        print("\n" + "!" * 60)
        print("AUTHENTICATION / CONNECTION FAILED:")
        print(str(exc))
        print("-" * 60)
        print("GMAIL INSTRUCTION:")
        print("Google rejects personal Google account passwords on SMTP and drops connection.")
        print("You must generate a 16-character Google App Password:")
        print("  1. Go to: https://myaccount.google.com/security")
        print("  2. Ensure 2-Step Verification is ON.")
        print("  3. Go to: https://myaccount.google.com/apppasswords")
        print("  4. Enter app name 'TrimTime' and click Create.")
        print("  5. Copy the 16-character password (e.g. 'abcd efgh ijkl mnop').")
        print("  6. Set SMTP_PASSWORD=<16_character_password> in your .env and Render settings.")
        print("!" * 60 + "\n")
        return False
    except Exception as exc:
        print(f"\nCONNECTION ERROR: {exc}\n")
        return False

if __name__ == "__main__":
    test_smtp()
