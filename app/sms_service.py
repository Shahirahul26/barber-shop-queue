import logging
import httpx
from .config import settings

logger = logging.getLogger(__name__)


def sms_is_configured() -> bool:
    return bool(settings.fast2sms_api_key)


def send_customer_otp_sms(phone: str, otp: str) -> None:
    if not settings.fast2sms_api_key:
        logger.info("Fast2SMS API key not configured. Customer OTP for %s: %s", phone, otp)
        return

    clean_phone = "".join(filter(str.isdigit, phone))[-10:]
    if len(clean_phone) != 10:
        logger.warning("Invalid phone number format for SMS OTP: %s", phone)
        return

    url = "https://www.fast2sms.com/dev/bulkV2"
    headers = {"authorization": settings.fast2sms_api_key}
    payload = {
        "variables_values": otp,
        "route": "otp",
        "numbers": clean_phone,
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, headers=headers, data=payload)
            data = response.json()
            if not data.get("return"):
                logger.warning("Fast2SMS dispatch failed for %s: %s", clean_phone, data.get("message"))
            else:
                logger.info("Fast2SMS OTP sent successfully to %s", clean_phone)
    except Exception as exc:
        logger.warning("Failed to send OTP SMS to %s via Fast2SMS: %s", phone, exc)

