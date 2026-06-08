import os
import requests
import time
from datetime import datetime
from services.base_service import BaseService
from models.email_record import EmailRecord
from utils.helpers import retry_api
from config import settings

class BrevoService(BaseService):
    """Integrates with Brevo transactional email (SMTP) API."""

    def __init__(self, api_key: str, mock_mode: bool = False):
        super().__init__("BrevoService", api_key, mock_mode)
        self.base_url = "https://api.brevo.com/v3/smtp/email"

    @retry_api(max_retries=3, initial_delay=2.0)
    def send_outreach_email(self, email_record: EmailRecord) -> bool:
        """Sends a single personalized cold outreach email."""
        if not self.validate_credentials():
            email_record.status = "FAILED"
            email_record.error_message = "Missing API key in live mode."
            return False

        if self.mock_mode:
            return self._simulate_send(email_record)

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        # Format the plain text body with HTML line breaks for standard email viewing
        html_content = email_record.body.replace("\n", "<br>")
        
        payload = {
            "sender": {
                "name": os.getenv("SENDER_NAME", "Naveen").strip(),
                "email": os.getenv("SENDER_EMAIL", "naveengowtham999@gmail.com").strip()
            },
            "to": [
                {
                    "email": email_record.recipient_email,
                    "name": email_record.contact_name
                }
            ],
            "subject": email_record.subject,
            "htmlContent": f"<html><body>{html_content}</body></html>"
        }

        self.logger.debug(f"[BrevoService] Transmitting email to '{email_record.recipient_email}'...")

        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 429:
                self.logger.warning("[BrevoService] Rate limit hit (429). Retrying via decorator...")
                raise requests.exceptions.HTTPError("429 Too Many Requests", response=response)
                
            response.raise_for_status()
            
            # Send successful
            email_record.status = "SENT"
            email_record.sent_at = datetime.now().isoformat()
            self.logger.debug(f"[BrevoService] Outreach successfully sent to {email_record.recipient_email}.")
            return True
            
        except requests.exceptions.RequestException as e:
            # Check if it was a client error (e.g. invalid email / bounce) or server error
            error_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg = error_details.get("message", error_msg)
                except ValueError:
                    pass
            
            email_record.status = "FAILED"
            email_record.error_message = error_msg
            self.logger.error(
                f"[BrevoService] Failed sending to {email_record.recipient_email}: {error_msg}"
            )
            # Re-raise so the retry decorator handles the backoff for server/network errors
            # (Don't re-raise for client mistakes like 400 Bad Request to avoid infinite retrying of invalid data)
            if hasattr(e, "response") and e.response is not None and e.response.status_code < 500 and e.response.status_code != 429:
                return False
            raise e

    def _simulate_send(self, email_record: EmailRecord) -> bool:
        """Simulates sending an email, logging the payload instead of executing HTTP calls."""
        self.logger.debug(f"[BrevoService] [SIMULATION] Sending email to {email_record.recipient_email}...")
        
        # Log content layout for interview demo
        sender_name = os.getenv("SENDER_NAME", "Naveen").strip()
        sender_email = os.getenv("SENDER_EMAIL", "naveengowtham999@gmail.com").strip()
        log_content = (
            f"\n------------------------------------------------------------\n"
            f" [SIMULATED EMAIL DISPATCH]\n"
            f" From: {sender_name} <{sender_email}>\n"
            f" To: {email_record.contact_name} <{email_record.recipient_email}>\n"
            f" Subject: {email_record.subject}\n"
            f" Body:\n{email_record.body}\n"
            f"------------------------------------------------------------"
        )
        if settings.DEBUG_MODE:
            self.logger.info(log_content)
        else:
            self.logger.debug(log_content)
        
        email_record.status = "SENT"
        email_record.sent_at = datetime.now().isoformat()
        return True
