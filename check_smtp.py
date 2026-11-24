"""
TrimTime SMTP Email Diagnostic Script
Run this script anytime to verify that SMTP email delivery is operational:
    python check_smtp.py
"""
import sys
from app.config import settings
from app.email_service import smtp_is_configured, test_smtp_connection

def main():
    print("=" * 65)
    print(" TrimTime SMTP Multi-Port Diagnostic Test")
    print("=" * 65)
    print(f"Host:         {settings.smtp_host}")
    print(f"Primary Port: {settings.smtp_port}")
    print(f"Username:     {settings.smtp_username}")
    print(f"Password:     {'*' * (len(settings.smtp_password) - 3) + settings.smtp_password[-3:] if len(settings.smtp_password) >= 3 else '***'}")
    print(f"From Email:   {settings.smtp_from_email or settings.smtp_username}")
    print("-" * 65)

    if not smtp_is_configured():
        print("FAIL: SMTP settings are incomplete.")
        print("Please configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, and SMTP_PASSWORD.")
        sys.exit(1)

    print("Testing connections and credentials across both SSL (465) and STARTTLS (587)...")
    res = test_smtp_connection(test_recipient=settings.smtp_username)
    
    print(f"Port 465 (Direct SSL):      {res['port_465_ssl']}")
    print(f"Port 587 (STARTTLS):        {res['port_587_starttls']}")
    print(f"Test Email Sent:            {'YES - ' + str(res.get('test_email_detail')) if res['test_email_sent'] else 'NO'}")
    print("-" * 65)

    if res["test_email_sent"]:
        print(f"SUCCESS: Verification test email delivered to {settings.smtp_username}!")
        print("Your TrimTime SMTP integration is working perfectly!")
        print("=" * 65)
        sys.exit(0)
    else:
        print("WARNING: Test email could not be delivered.")
        if "Authentication failed" in str(res.get("last_status")):
            print("Action: Ensure you are using a 16-character Google App Password from:")
            print("        https://myaccount.google.com/apppasswords")
        print("=" * 65)
        sys.exit(1)

if __name__ == "__main__":
    main()
