import requests
import time
from typing import List, Dict, Any, Optional
from services.base_service import BaseService
from models.contact import Contact
from utils.validators import validate_linkedin_url
from rich import print as rprint

def safe_strip(val) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        for k in ["name", "value", "url", "title"]:
            v = val.get(k)
            if isinstance(v, str):
                return v.strip()
        for k, v in val.items():
            if isinstance(v, str):
                return v.strip()
    if isinstance(val, list):
        if len(val) > 0:
            return safe_strip(val[0])
    return str(val).strip()

def extract_email_string(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        val_stripped = value.strip()
        if "@" in val_stripped:
            return val_stripped
        return None
    if isinstance(value, list):
        for item in value:
            extracted = extract_email_string(item)
            if extracted:
                return extracted
        return None
    if isinstance(value, dict):
        for key in ["email", "address", "value", "email_address"]:
            val = value.get(key)
            if val:
                extracted = extract_email_string(val)
                if extracted:
                    return extracted
        for k, v in value.items():
            if isinstance(v, str) and "@" in v:
                return v.strip()
            if isinstance(v, (dict, list)):
                extracted = extract_email_string(v)
                if extracted:
                    return extracted
        return None
    return None

class ProspeoService(BaseService):
    """Integrates with the real Prospeo search-person API to discover decision-makers."""

    def __init__(self, api_key: str, api_url: str = None, request_delay: float = None, max_retries: int = None, filter_by_job_title: bool = None):
        from config import settings
        # Initialize mock_mode based on the global settings.MOCK_MODE flag
        super().__init__("ProspeoService", api_key, mock_mode=settings.MOCK_MODE)
        self.base_url = api_url or "https://api.prospeo.io/search-person"
        self._schema_printed = False  # To print the raw response schema once in debug mode
        
        # Load from config settings if not explicitly passed
        from config import settings
        self.request_delay = request_delay if request_delay is not None else settings.PROSPEO_REQUEST_DELAY
        self.max_retries = max_retries if max_retries is not None else settings.PROSPEO_MAX_RETRIES
        self.filter_by_job_title = filter_by_job_title if filter_by_job_title is not None else settings.PROSPEO_FILTER_BY_JOB_TITLE

        # Statistics dictionary
        self.stats = {
            "Total Requests": 0,
            "Successful Requests": 0,
            "Rate Limited Requests": 0,
            "Failed Requests": 0
        }
        self.quota_depleted = False
        self.remaining_quota = 50


    def get_stats(self) -> Dict[str, int]:
        """Returns a copy of the request execution statistics."""
        stats_copy = self.stats.copy()
        if self.remaining_quota is not None:
            stats_copy["Remaining Quota"] = self.remaining_quota
        return stats_copy

    def _update_quota(self, response: requests.Response) -> None:
        if response is not None and hasattr(response, "headers"):
            left = response.headers.get("x-daily-request-left")
            if left is not None:
                try:
                    self.remaining_quota = int(left)
                    if self.remaining_quota <= 0:
                        self.quota_depleted = True
                except (ValueError, TypeError):
                    pass

    def find_contacts_for_company(self, domain: str, company_name: str, limit: int = 5) -> List[Contact]:
        """Queries Prospeo's search-person API for decision-makers at the given domain.
        
        Focuses on seniorities and titles like Founder, CEO, CTO, COO, VP, Director, and Head Of.
        """
        if self.mock_mode:
            self.logger.info(f"[Prospeo] [SIMULATION] Generating mock contacts for domain '{domain}'...")
            
            # Short delay in simulation mode to show progress without hanging the CLI
            time.sleep(0.1)
            self.stats["Total Requests"] += 1
            self.stats["Successful Requests"] += 1
            if self.remaining_quota is not None:
                self.remaining_quota -= 1
                if self.remaining_quota <= 0:
                    self.quota_depleted = True
            
            mock_people = [
                {"first": "Sarah", "last": "Jenkins", "title": "CEO & Founder"},
                {"first": "David", "last": "Miller", "title": "VP of Engineering"},
                {"first": "Elena", "last": "Rostova", "title": "Director of Product Management"},
                {"first": "Michael", "last": "Chang", "title": "CTO"},
                {"first": "Amanda", "last": "Smith", "title": "Head of People & Operations"}
            ]
            
            contacts_list = []
            for i, p in enumerate(mock_people[:limit]):
                first = p["first"]
                last = p["last"]
                full = f"{first} {last}"
                title = p["title"]
                linkedin = f"https://www.linkedin.com/in/{first.lower()}-{last.lower()}-{i}2345"
                
                contacts_list.append(Contact(
                    first_name=first,
                    last_name=last,
                    full_name=full,
                    designation=title,
                    linkedin_url=linkedin,
                    company_name=company_name,
                    company_domain=domain
                ))
                self.logger.info(f"[Prospeo] Contact Added: {full} ({title})")
                
            return contacts_list

        if self.quota_depleted:
            self.logger.warning(f"[Prospeo] Skipping contact search for domain '{domain}': Daily request quota is depleted.")
            return []

        if not self.validate_credentials():
            raise ValueError("[ProspeoService] Credentials validation failed. Please set a valid PROSPEO_API_KEY in .env.")

        headers = {
            "X-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        contacts: List[Contact] = []
        page = 1
        has_more = True
        seen_linkedin = set()

        initial_delay = 2.0
        backoff_factor = 2.0

        # Structured log: Real API Request Started
        self.logger.info(f"[Prospeo] Real API Request Started for domain: {domain}")

        # Targeted job titles for validation/filtering in code
        target_titles = ["founder", "ceo", "cto", "coo", "vp", "director", "head of"]
        
        reason = ""
        res_data = None

        try:
            while len(contacts) < limit and has_more:
                # Target company websites list within nested filters object
                payload = {
                    "filters": {
                        "company": {
                            "websites": {
                                "include": [domain]
                            }
                        }
                    },
                    "page": page
                }
                if self.filter_by_job_title:
                    payload["filters"]["person_job_title"] = {
                        "include": ["Founder", "CEO", "CTO", "COO", "VP", "Director", "Head Of"]
                    }

                res_data = None
                attempt_success = False

                for attempt in range(1, self.max_retries + 1):
                    # 1. Proactive throttling: Sleep PROSPEO_REQUEST_DELAY before EVERY request attempt
                    self.logger.info("[Prospeo] Request Throttled")
                    time.sleep(self.request_delay)

                    # Log: Retrying Request if attempt > 1
                    if attempt > 1:
                        self.logger.info("[Prospeo] Retrying Request")

                    try:
                        self.logger.debug(f"[Prospeo] POST Request to {self.base_url} (Page {page}, Domain: {domain}, Attempt {attempt})...")
                        
                        # Increment Total Requests statistic
                        self.stats["Total Requests"] += 1
                        
                        response = requests.post(self.base_url, json=payload, headers=headers, timeout=15)
                        self._update_quota(response)
                        
                        # Handle Prospeo's specific 400 NO_RESULTS response
                        if response.status_code == 400:
                            try:
                                err_json = response.json()
                                if err_json.get("error_code") == "NO_RESULTS":
                                    self.stats["Successful Requests"] += 1
                                    if attempt > 1:
                                        self.logger.info("[Prospeo] Retry Successful")
                                    reason = "API returned 400 NO_RESULTS"
                                    res_data = {"error": False, "results": []}
                                    attempt_success = True
                                    break
                            except Exception:
                                pass

                        if response.status_code == 429:
                            # 2. Increment Rate Limited Requests statistic
                            self.stats["Rate Limited Requests"] += 1
                            # Structured log: Rate Limit Detected
                            self.logger.warning("[Prospeo] Rate Limit Detected")
                            raise requests.exceptions.HTTPError("429 Too Many Requests", response=response)

                        response.raise_for_status()
                        
                        # Increment Successful Requests statistic
                        self.stats["Successful Requests"] += 1
                        if attempt > 1:
                            self.logger.info("[Prospeo] Retry Successful")

                        res_data = response.json()
                        attempt_success = True
                        break
                    except Exception as e:
                        # Determine if rate limit error
                        is_rate_limit = False
                        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                            if e.response.status_code == 429:
                                is_rate_limit = True

                        if is_rate_limit:
                            # Check if daily request limit is reached to fail fast
                            daily_left = e.response.headers.get("x-daily-request-left")
                            if daily_left == "0":
                                reset_seconds = e.response.headers.get("x-daily-reset-seconds", "86400")
                                self.logger.error(
                                    f"[Prospeo] Daily request quota depleted (0/50 left). "
                                    f"Resets in {reset_seconds} seconds. Skipping retries."
                                )
                                self.stats["Failed Requests"] += 1
                                reason = f"Daily request quota depleted. Resets in {reset_seconds}s"
                                self.quota_depleted = True
                                attempt_success = False
                                break

                        if not is_rate_limit:
                            # Increment Failed Requests statistic for non-429 errors
                            self.stats["Failed Requests"] += 1

                        if attempt == self.max_retries:
                            if is_rate_limit:
                                # Increment Failed Requests statistic since all retries on 429 exhausted
                                self.stats["Failed Requests"] += 1
                            reason = f"Request failed after {self.max_retries} attempts: {e}"
                            raise e
                        
                        # Calculate backoff delay
                        if is_rate_limit:
                            retry_after = e.response.headers.get("Retry-After")
                            if retry_after and retry_after.isdigit():
                                base_sleep = float(retry_after)
                            else:
                                # Backoffs mapping:
                                # Attempt 1 -> 10 seconds
                                # Attempt 2 -> 30 seconds
                                # Attempt 3 -> 60 seconds
                                # Attempt 4 -> 120 seconds
                                backoffs = {1: 10, 2: 30, 3: 60, 4: 120}
                                base_sleep = backoffs.get(attempt, 120.0)
                            
                            # Add random jitter (-1.0 to 1.0 seconds)
                            import random
                            jitter = random.uniform(-1.0, 1.0)
                            sleep_time = max(1.0, base_sleep + jitter)
                            
                            # Structured log: Waiting X Seconds (note the Capital 'S')
                            self.logger.info(f"[Prospeo] Waiting {int(sleep_time)} Seconds")
                        else:
                            # Exponential backoff for network or other non-429 exceptions
                            sleep_time = initial_delay * (backoff_factor ** (attempt - 1))
                            self.logger.warning(f"[Prospeo] Retry Attempt {attempt} for domain: {domain} due to error: {e}")
                        
                        time.sleep(sleep_time)

                if not attempt_success or not res_data:
                    if not reason:
                        reason = "API request was not successful"
                    break

                # Check for Prospeo API errors
                if res_data.get("error") is not False:
                    err_info = res_data.get("error")
                    err_msg = err_info if isinstance(err_info, str) else str(err_info)
                    if isinstance(err_info, dict):
                        err_msg = err_info.get("message", "Unknown Prospeo error")
                    reason = f"API returned error: {err_msg}"
                    raise ValueError(f"Prospeo API Error: {err_msg}")

                # Structured log: Real API Response Received
                self.logger.info(f"[Prospeo] Real API Response Received for domain: {domain}")

                # Print raw response schema once in debug mode
                if not self._schema_printed and res_data.get("results"):
                    import json
                    self.logger.debug(f"[Prospeo] Raw API Response Schema Sample:\n{json.dumps(res_data, indent=2)}")
                    self._schema_printed = True

                results = res_data.get("results", [])
                if not results:
                    if page == 1 and not reason:
                        reason = "API response returned zero results"
                    has_more = False
                    break

                # Structured log: Contacts Extracted (log that raw contacts were fetched on this page)
                self.logger.info(f"[Prospeo] Contacts Extracted: Found {len(results)} raw search results on page {page} for domain: {domain}")

                # Parse results
                for item in results:
                    p_data = item.get("person", {})
                    if not p_data:
                        continue

                    first = safe_strip(p_data.get("first_name"))
                    last = safe_strip(p_data.get("last_name"))
                    full = safe_strip(p_data.get("full_name"))
                    if not full:
                        full = safe_strip(f"{first} {last}")
                    title = safe_strip(p_data.get("current_job_title"))
                    linkedin = safe_strip(p_data.get("linkedin_url"))

                    p_company = item.get("company", {})
                    extracted_company = p_company.get("name", company_name) if p_company and p_company.get("name") else company_name

                    # Validate LinkedIn URL
                    if not linkedin or not validate_linkedin_url(linkedin):
                        self.logger.debug(f"[Prospeo] Skipping {full}: Missing or invalid LinkedIn URL ({linkedin})")
                        continue

                    # Filter/validate job title locally case-insensitively
                    title_lower = title.lower()
                    if not any(t in title_lower for t in target_titles):
                        self.logger.debug(f"[Prospeo] Skipping {full}: Job title '{title}' does not match target roles.")
                        continue

                    # Deduplicate at contact level (unique LinkedIn URL)
                    linkedin_lower = linkedin.lower()
                    if linkedin_lower in seen_linkedin:
                        continue
                    seen_linkedin.add(linkedin_lower)

                    # Show mapping of fields in debug mode
                    self.logger.debug(
                        f"[Prospeo] Mapping fields for Contact -> "
                        f"First: {first}, Last: {last}, Full: {full}, Title: {title}, "
                        f"LinkedIn: {linkedin}, Company: {extracted_company}, Domain: {domain}"
                    )

                    contact_obj = Contact(
                        first_name=first,
                        last_name=last,
                        full_name=full,
                        designation=title,
                        linkedin_url=linkedin,
                        company_name=extracted_company,
                        company_domain=domain
                    )
                    contacts.append(contact_obj)

                    # Structured log: Contact Added
                    self.logger.info(f"[Prospeo] Contact Added: {full} ({title})")

                    if len(contacts) >= limit:
                        break

                # Pagination handling
                pagination = res_data.get("pagination", {})
                current_page = pagination.get("current_page", 1)
                total_page = pagination.get("total_page", 1)

                if len(contacts) < limit and current_page < total_page:
                    page += 1
                    # Structured log: Pagination Next Page
                    self.logger.info(f"[Prospeo] Pagination Next Page: moving to page {page} for domain {domain}")
                else:
                    has_more = False

        except Exception as e:
            if not reason:
                reason = str(e)

        # Handle logging and returning if no contacts found
        if not contacts:
            if not reason:
                reason = "No matching contacts found after applying seniority filters"
            self.logger.info(f"[Prospeo] No Contacts Found for domain: {domain}. Reason: {reason}")
            return []

        # Print how many contacts were final-extracted
        self.logger.info(f"[Prospeo] Contacts Extracted: Successfully mapped {len(contacts)} contacts for domain: {domain}")
        return contacts[:limit]

    def resolve_email(self, linkedin_url: str, first_name: str = "", last_name: str = "", company_domain: str = "") -> Optional[str]:
        """Resolves a contact's work email using Prospeo's Enrich Person API."""
        if self.mock_mode:
            self.logger.info(f"[Prospeo] [SIMULATION] Resolving email for LinkedIn: {linkedin_url}...")
            time.sleep(0.1)
            self.stats["Total Requests"] += 1
            self.stats["Successful Requests"] += 1
            if self.remaining_quota is not None:
                self.remaining_quota -= 1
                if self.remaining_quota <= 0:
                    self.quota_depleted = True
            if not first_name and not last_name:
                return "mock.contact@example.com"
            import re
            first_clean = re.sub(r"[^a-zA-Z]", "", first_name).lower()
            last_clean = re.sub(r"[^a-zA-Z]", "", last_name).lower()
            domain_clean = company_domain.lower().strip() if company_domain else "example.com"
            return f"{first_clean}.{last_clean}@{domain_clean}"

        if self.quota_depleted:
            self.logger.warning(f"[Prospeo] Skipping email enrichment for '{linkedin_url}': Daily request quota is depleted.")
            return None

        if not self.validate_credentials():
            raise ValueError("[ProspeoService] Credentials validation failed. Please set a valid PROSPEO_API_KEY in .env.")

        headers = {
            "X-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "only_verified_email": False,
            "enrich_mobile": False,
            "data": {
                "linkedin_url": linkedin_url
            }
        }
        
        if first_name:
            payload["data"]["first_name"] = first_name
        if last_name:
            payload["data"]["last_name"] = last_name
        if company_domain:
            payload["data"]["company_website"] = company_domain

        self.logger.info(f"[Prospeo] Real API Enrichment Request Started for: {linkedin_url}")

        enrich_url = "https://api.prospeo.io/enrich-person"
        res_data = None
        attempt_success = False
        reason = ""

        for attempt in range(1, self.max_retries + 1):
            # Proactive throttling
            self.logger.info("[Prospeo] Request Throttled")
            time.sleep(self.request_delay)
            if attempt > 1:
                self.logger.info(f"[Prospeo] Retrying Enrichment Request (Attempt {attempt})...")

            try:
                self.stats["Total Requests"] += 1
                response = requests.post(enrich_url, json=payload, headers=headers, timeout=15)
                self._update_quota(response)

                if response.status_code == 429:
                    self.stats["Rate Limited Requests"] += 1
                    self.logger.warning("[Prospeo] Rate Limit Detected during enrichment")
                    raise requests.exceptions.HTTPError("429 Too Many Requests", response=response)

                response.raise_for_status()
                self.stats["Successful Requests"] += 1
                if attempt > 1:
                    self.logger.info("[Prospeo] Retry Successful")
                res_data = response.json()
                attempt_success = True
                break

            except Exception as e:
                is_rate_limit = False
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    if e.response.status_code == 429:
                        is_rate_limit = True

                if is_rate_limit:
                    daily_left = e.response.headers.get("x-daily-request-left")
                    if daily_left == "0":
                        reset_seconds = e.response.headers.get("x-daily-reset-seconds", "86400")
                        self.logger.error(
                            f"[Prospeo] Daily request quota depleted (0/50 left). "
                            f"Resets in {reset_seconds} seconds. Skipping retries."
                        )
                        self.stats["Failed Requests"] += 1
                        reason = f"Daily request quota depleted. Resets in {reset_seconds}s"
                        self.quota_depleted = True
                        attempt_success = False
                        break

                if not is_rate_limit:
                    self.stats["Failed Requests"] += 1

                if attempt == self.max_retries:
                    if is_rate_limit:
                        self.stats["Failed Requests"] += 1
                    reason = f"Request failed after {self.max_retries} attempts: {e}"
                    raise e

                # Calculate backoff delay
                if is_rate_limit:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        base_sleep = float(retry_after)
                    else:
                        backoffs = {1: 10, 2: 30, 3: 60, 4: 120}
                        base_sleep = backoffs.get(attempt, 120.0)
                    
                    import random
                    jitter = random.uniform(-1.0, 1.0)
                    sleep_time = max(1.0, base_sleep + jitter)
                    self.logger.info(f"[Prospeo] Waiting {int(sleep_time)} Seconds")
                else:
                    sleep_time = 2.0 * (2.0 ** (attempt - 1))
                    self.logger.warning(f"[Prospeo] Retry Attempt {attempt} for domain: {company_domain} due to error: {e}")
                
                time.sleep(sleep_time)

        if not attempt_success or not res_data:
            self.logger.info(f"[Prospeo] Email resolution failed for {linkedin_url}. Reason: {reason or 'Request unsuccessful'}")
            return None

        # Print raw response (Requirement 2)
        rprint(f"[bold magenta]Raw Prospeo Response:[/bold magenta] {res_data}")

        # Response schema validation (Requirement 8)
        is_valid_schema = False
        if isinstance(res_data, dict):
            if "error" in res_data:
                if res_data.get("error") is False:
                    if "person" in res_data:
                        is_valid_schema = True
                else:
                    is_valid_schema = True
            else:
                if "person" in res_data:
                    is_valid_schema = True
        
        if not is_valid_schema:
            self.logger.warning(f"[Prospeo] Response schema validation failed: {res_data}")

        # Save raw response to data/debug_prospeo_responses.json (Requirement 9)
        from pathlib import Path
        import json
        debug_file = Path("data/debug_prospeo_responses.json")
        try:
            debug_file.parent.mkdir(parents=True, exist_ok=True)
            responses_list = []
            if debug_file.exists():
                try:
                    with open(debug_file, "r", encoding="utf-8") as df:
                        responses_list = json.load(df)
                        if not isinstance(responses_list, list):
                            responses_list = []
                except Exception:
                    responses_list = []
            responses_list.append({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "linkedin_url": linkedin_url,
                "response": res_data
            })
            with open(debug_file, "w", encoding="utf-8") as df:
                json.dump(responses_list, df, indent=4)
        except Exception as de:
            self.logger.error(f"[Prospeo] Failed to save raw response to debug JSON: {de}")

        if isinstance(res_data, dict) and res_data.get("error") is not False:
            err_info = res_data.get("error")
            err_msg = err_info if isinstance(err_info, str) else str(err_info)
            if isinstance(err_info, dict):
                err_msg = err_info.get("message", "Unknown Prospeo error")
            self.logger.warning(f"[Prospeo] API error during email resolution: {err_msg}")
            return None

        # Parse email safely (Requirement 4, 5, 7)
        email = None
        try:
            if isinstance(res_data, dict):
                person_data = res_data.get("person", {})
                if isinstance(person_data, dict):
                    raw_email = person_data.get("email")
                    email = extract_email_string(raw_email)
                    
                    if email:
                        from utils.validators import validate_email_syntax
                        if not validate_email_syntax(email):
                            self.logger.warning(f"[Prospeo] Resolved email format is invalid: {email}")
                            email = None
        except Exception as pe:
            self.logger.error(f"[Prospeo] Crash prevented during email field parsing: {pe}")
            email = None

        # Add debug logging (Requirement 6)
        self.logger.info(f"Raw Prospeo Response: {res_data}")
        self.logger.info(f"Mapped Email: {email}")
        self.logger.info(f"Mapped LinkedIn: {linkedin_url}")

        return email
