from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Company:
    domain: str
    name: str
    company_size: str = ""
    primary_country: str = ""
    industries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "name": self.name,
            "company_size": self.company_size,
            "primary_country": self.primary_country,
            "industries": self.industries
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Company":
        return cls(
            domain=data.get("domain", ""),
            name=data.get("name", ""),
            company_size=data.get("company_size", ""),
            primary_country=data.get("primary_country", ""),
            industries=data.get("industries", [])
        )
