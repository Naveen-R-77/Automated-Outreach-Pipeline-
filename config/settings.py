import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Global Debug Mode Configuration
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# Ensure data and logs directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# API Keys and URLs
OCEAN_IO_API_KEY = os.getenv("OCEAN_IO_API_KEY", "").strip()
PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY", "").strip()
PROSPEO_API_URL = os.getenv("PROSPEO_API_URL", "https://api.prospeo.io/search-person").strip()
PROSPEO_REQUEST_DELAY = float(os.getenv("PROSPEO_REQUEST_DELAY", "5.0"))
PROSPEO_MAX_RETRIES = int(os.getenv("PROSPEO_MAX_RETRIES", "4"))
PROSPEO_CONTACTS_LIMIT = int(os.getenv("PROSPEO_CONTACTS_LIMIT", "10"))
PROSPEO_FILTER_BY_JOB_TITLE = os.getenv("PROSPEO_FILTER_BY_JOB_TITLE", "false").lower() == "true"
OCEAN_IO_MIN_COMPANY_SIZE = os.getenv("OCEAN_IO_MIN_COMPANY_SIZE", "11-50").strip()
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()

# Sender Details
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "naveengowtham999@gmail.com").strip()
SENDER_NAME = os.getenv("SENDER_NAME", "Naveen").strip()

# Queue & Delay Settings
EMAIL_BATCH_SIZE = int(os.getenv("EMAIL_BATCH_SIZE", "50"))
EMAIL_DELAY_SECONDS = float(os.getenv("EMAIL_DELAY_SECONDS", "2.0"))
BATCH_DELAY_SECONDS = float(os.getenv("BATCH_DELAY_SECONDS", "30.0"))

# Check if mock mode is requested globally or dynamically (defaults to False, updated by CLI flag)
MOCK_MODE = False

# Stage Files
CHECKPOINT_FILE = DATA_DIR / "checkpoint.json"
STAGE1_COMPANIES_FILE = DATA_DIR / "stage1_companies.json"
STAGE2_CONTACTS_FILE = DATA_DIR / "stage2_contacts.json"
FINAL_REPORT_FILE = DATA_DIR / "outreach_report.csv"

# Email Templates
EMAIL_SUBJECT_TEMPLATE = "Helping {company_name} scale outreach"
EMAIL_BODY_TEMPLATE = """Hi {contact_name},

I noticed your work as {designation} at {company_name}.

We have been studying how modern B2B teams scale their outbound sales operations. Given your focus on lead generation and outreach, I thought you might find it interesting to see how companies are automating their sourcing-to-mailing loops using consolidated data enrichment.

We've developed a modular pipeline that automatically sources lookalike companies, extracts C-level decision-makers, resolves work emails, and schedules personalized outreach in one step.

Would you be open to a quick 10-minute introduction next Tuesday or Thursday to discuss what workflows your team is currently using?

Best regards,

{sender_name}
Sales & Outreach Team
"""
