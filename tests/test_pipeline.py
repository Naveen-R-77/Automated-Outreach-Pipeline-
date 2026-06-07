import unittest
import sys
import json
import requests
import os
from pathlib import Path

# Add project root to sys.path to allow imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.validators import validate_email_syntax, validate_domain_syntax, validate_linkedin_url
from utils.helpers import save_json, load_json
from models.company import Company
from models.contact import Contact

class TestPipelineUtilities(unittest.TestCase):
    
    def test_email_validation(self) -> None:
        self.assertTrue(validate_email_syntax("sarah.jenkins@openai.com"))
        self.assertTrue(validate_email_syntax("ceo@anthropic.co"))
        self.assertFalse(validate_email_syntax("sarah.jenkins.openai.com"))
        self.assertFalse(validate_email_syntax("sarah.jenkins@"))
        self.assertFalse(validate_email_syntax(None))

    def test_domain_validation(self) -> None:
        self.assertTrue(validate_domain_syntax("openai.com"))
        self.assertTrue(validate_domain_syntax("subdomain.co.uk"))
        self.assertTrue(validate_domain_syntax("https://anthropic.com/info")) # strips protocol
        self.assertFalse(validate_domain_syntax("invalid_domain"))
        self.assertFalse(validate_domain_syntax(""))

    def test_linkedin_validation(self) -> None:
        self.assertTrue(validate_linkedin_url("https://www.linkedin.com/in/dario-amodei"))
        self.assertTrue(validate_linkedin_url("http://linkedin.com/in/daniela-amodei"))
        self.assertFalse(validate_linkedin_url("https://linkedin.com/in/"))
        self.assertFalse(validate_linkedin_url("https://linkedin.com/jobs"))

    def test_model_serialization(self) -> None:
        # Company
        comp = Company(domain="openai.com", name="OpenAI", company_size="500+", primary_country="US", industries=["AI"])
        comp_dict = comp.to_dict()
        self.assertEqual(comp_dict["domain"], "openai.com")
        self.assertEqual(comp_dict["industries"], ["AI"])
        
        comp_restored = Company.from_dict(comp_dict)
        self.assertEqual(comp_restored.name, "OpenAI")
        
        # Contact
        cont = Contact(
            first_name="Sam",
            last_name="Altman",
            full_name="Sam Altman",
            designation="CEO",
            linkedin_url="https://linkedin.com/in/samaltman",
            company_name="OpenAI",
            company_domain="openai.com",
            email="sam@openai.com",
            email_status="verified"
        )
        cont_dict = cont.to_dict()
        self.assertEqual(cont_dict["first_name"], "Sam")
        self.assertEqual(cont_dict["company_domain"], "openai.com")
        
        cont_restored = Contact.from_dict(cont_dict)
        self.assertEqual(cont_restored.full_name, "Sam Altman")
        self.assertEqual(cont_restored.email_status, "verified")

from unittest.mock import patch, MagicMock
from services.prospeo_service import ProspeoService

class TestProspeoService(unittest.TestCase):
    @patch('services.prospeo_service.requests.post')
    def test_daily_quota_depleted_fail_fast(self, mock_post) -> None:
        # Mock a 429 response indicating daily quota depleted
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {
            "x-daily-request-left": "0",
            "x-daily-reset-seconds": "100"
        }
        mock_post.return_value = mock_response

        # Instantiate service with a mock API key
        service = ProspeoService(api_key="mock_key", request_delay=0.01, max_retries=1)
        
        # Verify initial state
        self.assertFalse(service.quota_depleted)
        
        # Call for domain 1 (first company) - should call requests.post and hit quota limit
        contacts1 = service.find_contacts_for_company("domain1.com", "Company 1")
        self.assertEqual(contacts1, [])
        self.assertTrue(service.quota_depleted)
        self.assertEqual(mock_post.call_count, 1)
        
        # Call for domain 2 (second company) - should fail-fast without calling requests.post
        mock_post.reset_mock()
        contacts2 = service.find_contacts_for_company("domain2.com", "Company 2")
        self.assertEqual(contacts2, [])
        self.assertEqual(mock_post.call_count, 0)

    @patch('services.prospeo_service.requests.post')
    def test_filter_by_job_title_configuration(self, mock_post) -> None:
        # Mock a 200 response with empty results
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": False, "results": []}
        mock_post.return_value = mock_response

        # Case 1: filter_by_job_title = True
        service_with_filter = ProspeoService(api_key="mock_key", request_delay=0.01, max_retries=1, filter_by_job_title=True)
        service_with_filter.find_contacts_for_company("example.com", "Example")
        
        self.assertEqual(mock_post.call_count, 1)
        sent_payload_with = mock_post.call_args[1]["json"]
        self.assertIn("person_job_title", sent_payload_with["filters"])

        # Case 2: filter_by_job_title = False
        mock_post.reset_mock()
        service_without_filter = ProspeoService(api_key="mock_key", request_delay=0.01, max_retries=1, filter_by_job_title=False)
        service_without_filter.find_contacts_for_company("example.com", "Example")
        
        self.assertEqual(mock_post.call_count, 1)
        sent_payload_without = mock_post.call_args[1]["json"]
        self.assertNotIn("person_job_title", sent_payload_without["filters"])

class TestMockMode(unittest.TestCase):
    def test_ocean_service_mock_mode(self) -> None:
        from config import settings
        original_mock_mode = settings.MOCK_MODE
        try:
            settings.MOCK_MODE = True
            from services.ocean_service import OceanService
            service = OceanService(api_key="anything")
            self.assertTrue(service.mock_mode)
            companies = service.find_similar_companies("leetcode.com", limit=3)
            self.assertEqual(len(companies), 3)
            self.assertEqual(companies[0].domain, "sololearn.com")
        finally:
            settings.MOCK_MODE = original_mock_mode

    def test_prospeo_service_mock_mode(self) -> None:
        from config import settings
        original_mock_mode = settings.MOCK_MODE
        try:
            settings.MOCK_MODE = True
            from services.prospeo_service import ProspeoService
            service = ProspeoService(api_key="anything", request_delay=0.01)
            self.assertTrue(service.mock_mode)
            contacts = service.find_contacts_for_company("sololearn.com", "Sololearn", limit=2)
            self.assertEqual(len(contacts), 2)
            self.assertEqual(contacts[0].first_name, "Sarah")
        finally:
            settings.MOCK_MODE = original_mock_mode


class TestOceanService(unittest.TestCase):
    @patch('services.ocean_service.requests.post')
    def test_ocean_service_403_forbidden(self, mock_post) -> None:
        # Mock a 403 response
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Plan limit exceeded"
        mock_post.return_value = mock_response

        from services.ocean_service import OceanService
        service = OceanService(api_key="mock_key")
        service.mock_mode = False

        with self.assertRaises(requests.exceptions.HTTPError) as ctx:
            service.find_similar_companies("openai.com", limit=5)
        
        self.assertIn("Ocean.io plan does not permit this endpoint", str(ctx.exception))


class TestProspeoEmailResolution(unittest.TestCase):
    def test_mock_mode_resolve_email(self) -> None:
        from services.prospeo_service import ProspeoService
        from config import settings
        original_mock_mode = settings.MOCK_MODE
        try:
            settings.MOCK_MODE = True
            service = ProspeoService(api_key="anything", request_delay=0.01)
            email = service.resolve_email(
                linkedin_url="https://linkedin.com/in/sarah-jenkins",
                first_name="Sarah",
                last_name="Jenkins",
                company_domain="sololearn.com"
            )
            self.assertEqual(email, "sarah.jenkins@sololearn.com")
        finally:
            settings.MOCK_MODE = original_mock_mode

    @patch('services.prospeo_service.requests.post')
    def test_real_mode_resolve_email_success(self, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": False,
            "person": {
                "email": "sarah.jenkins@sololearn.com",
                "email_status": "verified"
            }
        }
        mock_post.return_value = mock_response

        from services.prospeo_service import ProspeoService
        service = ProspeoService(api_key="real_key", request_delay=0.01, max_retries=1)
        service.mock_mode = False

        email = service.resolve_email(
            linkedin_url="https://linkedin.com/in/sarah-jenkins",
            first_name="Sarah",
            last_name="Jenkins",
            company_domain="sololearn.com"
        )
        self.assertEqual(email, "sarah.jenkins@sololearn.com")

    @patch('services.prospeo_service.requests.post')
    def test_real_mode_resolve_email_null(self, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": False,
            "person": {
                "email": None
            }
        }
        mock_post.return_value = mock_response

        from services.prospeo_service import ProspeoService
        service = ProspeoService(api_key="real_key", request_delay=0.01, max_retries=1)
        service.mock_mode = False

        email = service.resolve_email(
            linkedin_url="https://linkedin.com/in/sarah-jenkins",
            first_name="Sarah",
            last_name="Jenkins",
            company_domain="sololearn.com"
        )
        self.assertIsNone(email)

    def test_extract_email_string_handling(self) -> None:
        from services.prospeo_service import extract_email_string, safe_strip
        
        # Strings
        self.assertEqual(extract_email_string("  test@domain.com  "), "test@domain.com")
        # Null values
        self.assertIsNone(extract_email_string(None))
        # Dictionaries
        self.assertEqual(extract_email_string({"email": "john@example.com"}), "john@example.com")
        self.assertEqual(extract_email_string({"value": "jane@example.com"}), "jane@example.com")
        self.assertEqual(extract_email_string({"some_other_key": "somebody@example.com"}), "somebody@example.com")
        # Arrays
        self.assertEqual(extract_email_string(["other", "test@example.com"]), "test@example.com")
        # Nested structures
        self.assertEqual(extract_email_string([{"email": "nested@example.com"}]), "nested@example.com")
        
        # safe_strip
        self.assertEqual(safe_strip("  abc  "), "abc")
        self.assertEqual(safe_strip(None), "")
        self.assertEqual(safe_strip({"name": "  xyz  "}), "xyz")
        self.assertEqual(safe_strip(["  def  "]), "def")

    @patch('main.sys.exit')
    @patch('main.generate_final_report')
    @patch('main.clear_checkpoint')
    @patch('main.rprint')
    @patch('main.logger')
    def test_missing_sender_email_stops_stage_3_gracefully(self, mock_logger, mock_rprint, mock_clear_checkpoint, mock_generate_report, mock_exit) -> None:
        import main
        from config import settings
        
        original_mock_mode = settings.MOCK_MODE
        original_sender_email = os.environ.get("SENDER_EMAIL")
        
        try:
            settings.MOCK_MODE = False
            if "SENDER_EMAIL" in os.environ:
                del os.environ["SENDER_EMAIL"]
                
            with patch('main.argparse.ArgumentParser.parse_args') as mock_args, \
                 patch('main.load_checkpoint') as mock_load_checkpoint, \
                 patch('main.load_json') as mock_load_json, \
                 patch('main.Prompt.ask', return_value="y") as mock_prompt:
                 
                mock_args_obj = MagicMock()
                mock_args_obj.resume = True
                mock_args_obj.dry_run = False
                mock_args_obj.mock = False
                mock_args.return_value = mock_args_obj
                
                mock_load_checkpoint.return_value = {
                    "seed_domain": "example.com",
                    "last_completed_stage": 2
                }
                
                mock_load_json.side_effect = [
                    [{"domain": "example.com", "name": "Example"}],
                    [{"first_name": "Sarah", "last_name": "Jenkins", "full_name": "Sarah Jenkins", "designation": "CEO", "linkedin_url": "https://linkedin.com/in/sarah-jenkins", "company_name": "Example", "company_domain": "example.com", "email": "sarah@example.com", "email_status": "verified"}]
                ]
                
                mock_exit.side_effect = SystemExit
                
                with self.assertRaises(SystemExit):
                    main.run_pipeline()
                
                mock_rprint.assert_any_call("[bold red]Sender email not configured[/bold red]")
                mock_exit.assert_called_with(0)
                mock_clear_checkpoint.assert_called_once()
                mock_generate_report.assert_called_once()
                
        finally:
            settings.MOCK_MODE = original_mock_mode
            if original_sender_email is not None:
                os.environ["SENDER_EMAIL"] = original_sender_email

    @patch('main.rprint')
    @patch('main.load_checkpoint')
    @patch('main.load_json')
    @patch('main.save_json')
    @patch('main.save_checkpoint')
    def test_prospeo_quota_exhaustion_stops_stage_2_immediately(self, mock_save_checkpoint, mock_save_json, mock_load_json, mock_load_checkpoint, mock_rprint) -> None:
        import main
        from config import settings
        from services.prospeo_service import ProspeoService
        
        original_mock_mode = settings.MOCK_MODE
        try:
            settings.MOCK_MODE = False
            
            with patch('main.argparse.ArgumentParser.parse_args') as mock_args, \
                 patch('main.ProspeoService') as MockProspeoService:
                 
                mock_args_obj = MagicMock()
                mock_args_obj.resume = True
                mock_args_obj.dry_run = True
                mock_args_obj.mock = False
                mock_args.return_value = mock_args_obj
                
                mock_load_checkpoint.return_value = {
                    "seed_domain": "example.com",
                    "last_completed_stage": 1
                }
                
                # Mock companies loaded from Stage 1: 3 companies
                mock_load_json.return_value = [
                    {"domain": "comp1.com", "name": "Comp1"},
                    {"domain": "comp2.com", "name": "Comp2"},
                    {"domain": "comp3.com", "name": "Comp3"}
                ]
                
                # Instantiate mock prospeo service
                mock_service_instance = MagicMock()
                mock_service_instance.mock_mode = False
                mock_service_instance.quota_depleted = False
                mock_service_instance.remaining_quota = 50
                
                # Sourcing contacts: Comp1 returns contacts, but then quota depletes
                contact1 = Contact(
                    first_name="Sarah", last_name="Jenkins", full_name="Sarah Jenkins",
                    designation="CEO", linkedin_url="https://linkedin.com/in/sarah-jenkins",
                    company_name="Comp1", company_domain="comp1.com"
                )
                
                def mock_find_contacts(domain, company_name, limit):
                    if domain == "comp1.com":
                        return [contact1]
                    return []
                
                mock_service_instance.find_contacts_for_company.side_effect = mock_find_contacts
                
                # Resolve email for contact1 depletes quota
                def mock_resolve_email(linkedin_url, first_name, last_name, company_domain):
                    mock_service_instance.quota_depleted = True
                    mock_service_instance.remaining_quota = 0
                    return None
                    
                mock_service_instance.resolve_email.side_effect = mock_resolve_email
                mock_service_instance.get_stats.return_value = {}
                
                MockProspeoService.return_value = mock_service_instance
                
                with patch('main.sys.exit') as mock_exit:
                    main.run_pipeline()
                
                # Check that rprint was called with PROSPEO QUOTA EXHAUSTED
                mock_rprint.assert_any_call("\n[bold red]PROSPEO QUOTA EXHAUSTED[/bold red]")
                # Verify find_contacts_for_company was only called for comp1.com and not comp2.com or comp3.com
                self.assertEqual(mock_service_instance.find_contacts_for_company.call_count, 1)
                mock_service_instance.find_contacts_for_company.assert_called_with(
                    domain="comp1.com",
                    company_name="Comp1",
                    limit=settings.PROSPEO_CONTACTS_LIMIT
                )
        finally:
            settings.MOCK_MODE = original_mock_mode

    def test_adaptive_limits(self) -> None:
        import main
        from config import settings
        from services.prospeo_service import ProspeoService
        
        with patch('main.argparse.ArgumentParser.parse_args') as mock_args, \
             patch('main.load_checkpoint') as mock_load_checkpoint, \
             patch('main.load_json') as mock_load_json, \
             patch('main.save_json'), \
             patch('main.save_checkpoint'), \
             patch('main.rprint'), \
             patch('main.sys.exit'), \
             patch('main.ProspeoService') as MockProspeoService:
             
            mock_args_obj = MagicMock()
            mock_args_obj.resume = True
            mock_args_obj.dry_run = True
            mock_args_obj.mock = False
            mock_args.return_value = mock_args_obj
            
            mock_load_checkpoint.return_value = {
                "seed_domain": "example.com",
                "last_completed_stage": 1
            }
            
            # Load 2 companies
            mock_load_json.return_value = [
                {"domain": "comp1.com", "name": "Comp1"},
                {"domain": "comp2.com", "name": "Comp2"}
            ]
            
            mock_service_instance = MagicMock()
            mock_service_instance.mock_mode = False
            mock_service_instance.quota_depleted = False
            mock_service_instance.get_stats.return_value = {}
            MockProspeoService.return_value = mock_service_instance
            
            mock_service_instance.remaining_quota = 9
            mock_service_instance.find_contacts_for_company.return_value = []
            
            def mock_find_contacts_adapter(domain, company_name, limit):
                if domain == "comp1.com":
                    self.assertEqual(limit, 3)
                    mock_service_instance.remaining_quota = 4
                elif domain == "comp2.com":
                    self.assertEqual(limit, 1)
                return []
            mock_service_instance.find_contacts_for_company.side_effect = mock_find_contacts_adapter
            
            main.run_pipeline()

    @patch('main.OceanService')
    @patch('main.Prompt.ask', return_value="leetcode.com")
    def test_cli_limit_argument(self, mock_prompt_ask, MockOceanService) -> None:
        import main
        from config import settings
        
        original_mock_mode = settings.MOCK_MODE
        try:
            settings.MOCK_MODE = False
            
            with patch('main.argparse.ArgumentParser.parse_args') as mock_args, \
                 patch('main.sys.exit') as mock_exit, \
                 patch('main.save_json'), \
                 patch('main.save_checkpoint'):
                 
                mock_args_obj = MagicMock()
                mock_args_obj.resume = False
                mock_args_obj.dry_run = True
                mock_args_obj.mock = False
                mock_args_obj.limit = 7
                mock_args.return_value = mock_args_obj
                
                mock_ocean_instance = MagicMock()
                mock_ocean_instance.find_similar_companies.return_value = []
                MockOceanService.return_value = mock_ocean_instance
                
                mock_exit.side_effect = SystemExit
                
                with self.assertRaises(SystemExit):
                    main.run_pipeline()
                
                mock_ocean_instance.find_similar_companies.assert_called_once_with(
                    "leetcode.com",
                    limit=7
                )
        finally:
            settings.MOCK_MODE = original_mock_mode




if __name__ == "__main__":
    unittest.main()
