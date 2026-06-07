import re

# Standard B2B email validation regex
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# Standard domain validation regex (e.g. google.com, subdomain.example.co.uk)
DOMAIN_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$"
)

# LinkedIn profile URL regex
LINKEDIN_REGEX = re.compile(
    r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?$"
)

def validate_email_syntax(email: str) -> bool:
    """Returns True if the email matches standard structural patterns."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))

def validate_domain_syntax(domain: str) -> bool:
    """Returns True if the domain matches valid structure (excluding protocols/paths)."""
    if not domain or not isinstance(domain, str):
        return False
    # Strip protocol if accidentally entered
    cleaned_domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
    return bool(DOMAIN_REGEX.match(cleaned_domain.strip()))

def validate_linkedin_url(url: str) -> bool:
    """Returns True if the URL points to a valid public LinkedIn profile."""
    if not url or not isinstance(url, str):
        return False
    return bool(LINKEDIN_REGEX.match(url.strip()))
