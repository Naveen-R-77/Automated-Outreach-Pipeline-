import requests
from typing import List, Dict, Any
from services.base_service import BaseService
from models.company import Company
from utils.helpers import retry_api

class OceanService(BaseService):
    """Integrates with Ocean.io API for live B2B lookalike company discovery."""
    
    def __init__(self, api_key: str):
        from config import settings
        # Pass settings.MOCK_MODE to base class initialization
        super().__init__("OceanService", api_key, mock_mode=settings.MOCK_MODE)
        self.base_url = "https://api.ocean.io/v3/search/companies"

    @retry_api(max_retries=3, initial_delay=2.0)
    def find_similar_companies(self, seed_domain: str, limit: int = 25) -> List[Company]:
        """Queries Ocean.io for similar lookalike company domains."""
        # Extract the brand name from seed domain to avoid parent company redirects (duplicates)
        seed_brand = seed_domain.split(".")[0].lower() # e.g. "google" from "google.com"

        if self.mock_mode:
            self.logger.info(f"[OceanService] [SIMULATION] Generating {limit} mock lookalike companies for domain '{seed_domain}'...")
            mock_names = [
                "Sololearn", "Qualified.io", "HackerRank", "Coderbyte", "Codewars", 
                "Sphere Engine", "Codility", "CodeSignal", "FreeCodeCamp", "Code.org", 
                "TestDome", "DataCamp", "Karat", "SkillsUnion", "Triplebyte", 
                "StarkSeek", "CodeforgePrep", "Crakcode", "TechGig", "TutorialsPoint", 
                "Nuwe.io", "Codolog", "GeekTrust", "GeeksforGeeks", "CodinGame"
            ]
            mock_domains = [
                "sololearn.com", "qualified.io", "hackerrank.com", "coderbyte.com", "codewars.com", 
                "sphere-engine.com", "codility.com", "codesignal.com", "freecodecamp.org", "code.org", 
                "testdome.com", "datacamp.com", "karat.com", "skillsunion.com", "triplebyte.com", 
                "starkseek.com", "codeforgeprep.com", "crakcode.in", "techgig.com", "tutorialspoint.com", 
                "nuwe.io", "codolog.in", "geektrust.com", "geeksforgeeks.org", "codingame.com"
            ]
            mock_sizes = [
                "11-50", "51-200", "201-500", "501-1000", "1001-5000", "10001-50000"
            ]
            mock_countries = ["us", "gb", "in", "de", "ca", "au"]
            mock_industries = ["E-Commerce", "Software", "Skill Assessment", "EdTech", "Artificial Intelligence"]
            
            companies = []
            for i in range(min(limit, len(mock_domains))):
                domain = mock_domains[i]
                name = mock_names[i]
                
                # Exclude duplicate / alternate domains of the seed company itself
                if seed_brand in domain.lower() or seed_brand in name.lower():
                    continue
                    
                companies.append(Company(
                    domain=domain,
                    name=name,
                    company_size=mock_sizes[i % len(mock_sizes)],
                    primary_country=mock_countries[i % len(mock_countries)],
                    industries=[mock_industries[i % len(mock_industries)], "Information Technology"]
                ))
            return companies[:limit]

        if not self.validate_credentials():
            raise ValueError("[OceanService] Credentials validation failed. Please set a valid OCEAN_IO_API_KEY in .env.")

        headers = {
            "X-Api-Token": self.api_key,
            "Content-Type": "application/json"
        }
        
        companies: List[Company] = []
        search_after = None
        has_more = True
        
        # Configure company size filters dynamically based on settings
        from config import settings
        all_brackets = [
            '0-1', '2-10', '11-50', '51-200', '201-500', '501-1000', 
            '1001-5000', '5001-10000', '10001-50000', '50001-100000', 
            '100001-500000', '500000+'
        ]
        min_size = settings.OCEAN_IO_MIN_COMPANY_SIZE
        if min_size in all_brackets:
            idx = all_brackets.index(min_size)
            allowed_brackets = all_brackets[idx:]
        else:
            allowed_brackets = all_brackets

        # Structured log: API request start
        self.logger.info(f"[OceanService] API Request starting for domain: '{seed_domain}' (target limit: {limit})...")

        while len(companies) < limit and has_more:
            # Batch size is the minimum of remaining limit and 50
            batch_size = min(limit - len(companies), 50)
            
            payload: Dict[str, Any] = {
                "size": batch_size,
                "fields": ["domain", "name", "companySize", "primaryCountry", "industries"],
                "companiesFilters": {
                    "lookalikeDomains": [seed_domain],
                    "companySizes": allowed_brackets
                }
            }
            
            if search_after:
                payload["searchAfter"] = search_after

            try:
                self.logger.debug(f"[OceanService] POST Request to {self.base_url} with size={batch_size}...")
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=12)
                
                # Check for 403 Forbidden (billing/plan limits)
                if response.status_code == 403:
                    error_msg = response.text
                    try:
                        err_json = response.json()
                        if isinstance(err_json, dict):
                            error_msg = err_json.get("message") or err_json.get("error") or str(err_json)
                    except Exception:
                        pass
                    self.logger.error(f"[OceanService] API 403 Forbidden: {error_msg}")
                    raise requests.exceptions.HTTPError("Ocean.io plan does not permit this endpoint", response=response)

                # Check for rate limits (429)
                if response.status_code == 429:
                    # Structured log: Rate limit handling
                    self.logger.warning("[OceanService] API Rate Limit (429) received. Triggering backoff retry...")
                    raise requests.exceptions.HTTPError("429 Too Many Requests", response=response)
                    
                response.raise_for_status()
                res_data = response.json()
                
                company_list = res_data.get("companies", [])
                
                # Structured log: API success
                self.logger.info(
                    f"[OceanService] API Success: Sourced {len(company_list)} lookalikes in this batch. "
                    f"Total accumulated so far: {len(companies) + len(company_list)}"
                )
                
                # Parse companies
                for item in company_list:
                    c_data = item.get("company", {})
                    domain = c_data.get("domain", "")
                    name = c_data.get("name", "")
                    
                    # Exclude duplicate / alternate domains of the seed company itself
                    if seed_brand in domain.lower() or seed_brand in name.lower():
                        self.logger.debug(f"[OceanService] Skipping {domain} ({name}): Duplicate of seed brand '{seed_brand}'")
                        continue

                    companies.append(Company(
                        domain=domain,
                        name=name,
                        company_size=c_data.get("companySize", ""),
                        primary_country=c_data.get("primaryCountry", ""),
                        industries=c_data.get("industries", [])
                    ))
                
                # Pagination cursor update
                search_after = res_data.get("searchAfter")
                has_more = bool(search_after) and len(company_list) > 0
                
            except requests.exceptions.RequestException as e:
                # Structured log: API failure
                self.logger.error(f"[OceanService] API Failure on search endpoint: {e}")
                raise e

        # Apply Company Level Deduplication (ensure unique domains)
        unique_companies = []
        seen_domains = set()
        for comp in companies[:limit]:
            if comp.domain and comp.domain.lower() not in seen_domains:
                seen_domains.add(comp.domain.lower())
                unique_companies.append(comp)
                
        self.logger.info(f"[OceanService] Sourced {len(unique_companies)} unique lookalike companies.")
        return unique_companies
