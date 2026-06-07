from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime

@dataclass
class EmailRecord:
    contact_name: str
    company_name: str
    recipient_email: str
    subject: str = ""
    body: str = ""
    sent_at: Optional[str] = None
    status: str = "PENDING"  # PENDING, SENT, FAILED, SKIPPED (dry run)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact_name": self.contact_name,
            "company_name": self.company_name,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "body": self.body,
            "sent_at": self.sent_at,
            "status": self.status,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailRecord":
        return cls(
            contact_name=data.get("contact_name", ""),
            company_name=data.get("company_name", ""),
            recipient_email=data.get("recipient_email", ""),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            sent_at=data.get("sent_at"),
            status=data.get("status", "PENDING"),
            error_message=data.get("error_message")
        )

    def personalize(self, subject_template: str, body_template: str, designation: str, sender_name: str) -> None:
        """Helper to fill in subject and body templates dynamically."""
        self.subject = subject_template.format(
            company_name=self.company_name,
            contact_name=self.contact_name,
            designation=designation
        )
        self.body = body_template.format(
            company_name=self.company_name,
            contact_name=self.contact_name,
            designation=designation,
            sender_name=sender_name
        )
