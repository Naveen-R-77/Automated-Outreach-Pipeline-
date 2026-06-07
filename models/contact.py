from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class Contact:
    """Represents a lead/prospect contact sourced from the pipeline.
    
    Fields:
        first_name: Person's first name
        last_name: Person's last name
        full_name: Person's full name
        designation: Person's job title/role (e.g. CEO, Founder)
        linkedin_url: Link to public LinkedIn profile
        company_name: Name of their employer company
        company_domain: Company's domain website
        email: Contact email address (populated in Stage 2)
        email_status: Verification state of email
    """
    first_name: str
    last_name: str
    full_name: str
    designation: str
    linkedin_url: str
    company_name: str
    company_domain: str = ""
    email: Optional[str] = None
    email_status: str = "unresolved"  # unresolved, verified, invalid, duplicate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "designation": self.designation,
            "linkedin_url": self.linkedin_url,
            "company_name": self.company_name,
            "company_domain": self.company_domain,
            "email": self.email,
            "email_status": self.email_status
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contact":
        return cls(
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            full_name=data.get("full_name", ""),
            designation=data.get("designation", ""),
            linkedin_url=data.get("linkedin_url", ""),
            company_name=data.get("company_name", ""),
            company_domain=data.get("company_domain", ""),
            email=data.get("email", None),
            email_status=data.get("email_status", "unresolved")
        )
