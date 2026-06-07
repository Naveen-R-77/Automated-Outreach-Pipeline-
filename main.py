import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
import requests
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Prompt, Confirm
from rich import print as rprint

from config import settings
from utils.logger import logger
from utils.validators import validate_domain_syntax, validate_email_syntax
from utils.helpers import (
    save_json, load_json, save_csv,
    save_checkpoint, load_checkpoint, clear_checkpoint
)
from models.company import Company
from models.contact import Contact
from models.email_record import EmailRecord

from services.ocean_service import OceanService
from services.prospeo_service import ProspeoService
from services.brevo_service import BrevoService

console = Console()

def generate_final_report(total_companies, total_contacts, total_emails, sent_count=0, fail_count=0, skipped_count=0):
    report_data = {
        "companies_found": total_companies,
        "contacts_found": total_contacts,
        "emails_found": total_emails,
        "emails_sent": sent_count,
        "emails_failed": fail_count,
        "emails_skipped": skipped_count
    }
    report_path = settings.PROJECT_ROOT / "pipeline_report.json"
    save_json(report_path, report_data)
    logger.info(f"[Pipeline] Sourced and saved final pipeline report to {report_path}")

def run_pipeline():
    # Parse CLI options
    parser = argparse.ArgumentParser(
        description="Automated Outreach Pipeline - Production B2B Cold Outreach Engine"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the entire sourcing pipeline but skip sending emails. Shows what would be sent."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume pipeline from the last completed stage using data/checkpoint.json."
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force the pipeline into mock/simulation mode for testing without using real API tokens."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Default Ocean.io company lookup limit."
    )
    args = parser.parse_args()

    # Override mock mode configuration in settings dynamically
    if args.mock:
        settings.MOCK_MODE = True
        logger.warning("[Pipeline] --mock flag detected. Forcing mock simulation globally.")
    else:
        settings.MOCK_MODE = False

    # Initialize Services
    ocean_service = OceanService(settings.OCEAN_IO_API_KEY)
    prospeo_service = ProspeoService(
        api_key=settings.PROSPEO_API_KEY,
        api_url=settings.PROSPEO_API_URL,
        request_delay=settings.PROSPEO_REQUEST_DELAY,
        max_retries=settings.PROSPEO_MAX_RETRIES
    )
    brevo_service = BrevoService(settings.BREVO_API_KEY)

    # State variables
    seed_domain = None
    companies = []
    contacts = []
    start_stage = 1

    # Checkpoint recovery
    if args.resume:
        checkpoint = load_checkpoint()
        if not checkpoint:
            rprint("[bold red]Error: No valid checkpoint found to resume from.[/bold red]")
            logger.error("[Pipeline] Resume failed: data/checkpoint.json is missing or empty.")
            sys.exit(1)
        
        seed_domain = checkpoint.get("seed_domain")
        last_completed = checkpoint.get("last_completed_stage", 0)
        start_stage = last_completed + 1
        
        rprint(f"[bold green]Resuming pipeline for seed domain '{seed_domain}' from Stage {start_stage}...[/bold green]")
        
        # Load previous stage files
        if start_stage > 1:
            comp_data = load_json(settings.STAGE1_COMPANIES_FILE)
            if comp_data:
                companies = [Company.from_dict(c) for c in comp_data]
                logger.info(f"[Pipeline] Loaded {len(companies)} companies from Stage 1 cache.")
        if start_stage > 2:
            cont_data = load_json(settings.STAGE2_CONTACTS_FILE)
            if cont_data:
                contacts = [Contact.from_dict(c) for c in cont_data]
                logger.info(f"[Pipeline] Loaded {len(contacts)} contacts from Stage 2 cache.")
    else:
        # Standard run, clear any previous checkpoint
        clear_checkpoint()

    # Get input domain if not resuming
    if not seed_domain:
        rprint("\n[bold cyan]============================================================[/bold cyan]")
        rprint("[bold cyan]       Welcome to the Automated Outreach Pipeline           [/bold cyan]")
        rprint("[bold cyan]============================================================[/bold cyan]\n")
        
        seed_domain = Prompt.ask(
            "[bold white]Enter target company domain (e.g., openai.com)[/bold white]"
        ).strip()
        
        while not validate_domain_syntax(seed_domain):
            rprint("[bold red]Invalid domain syntax. Please enter a valid domain (e.g. example.com).[/bold red]")
            seed_domain = Prompt.ask("[bold white]Re-enter company domain[/bold white]").strip()
        
        logger.info(f"[Pipeline] Seed domain set to: {seed_domain}")

    # ==========================================
    # STAGE 1: Ocean.io
    # ==========================================
    if start_stage <= 1:
        rprint("\n[bold cyan]Stage 1 Started...[/bold cyan]")
        logger.info("[Pipeline] Starting Stage 1: Ocean.io")
        with console.status("[bold green]Discovering lookalike companies via Ocean.io...[/bold green]", spinner="dots") as status:
            try:
                # Find lookalike companies (limit dynamically set via CLI limit parameter)
                raw_companies = ocean_service.find_similar_companies(seed_domain, limit=args.limit)
                
                # Company-level de-duplication (unique domains)
                seen_domains = set()
                for comp in raw_companies:
                    if comp.domain.lower() not in seen_domains:
                        seen_domains.add(comp.domain.lower())
                        companies.append(comp)
                # Save Stage Output
                save_json(settings.STAGE1_COMPANIES_FILE, [c.to_dict() for c in companies])
                save_checkpoint(seed_domain, 1)
                
                rprint("[bold green]Ocean.io Search Complete[/bold green]")
                rprint(f"[bold green]{len(companies)} Similar Companies Found[/bold green]")
                rprint("[bold green]Stage 1 Output Saved[/bold green]\n")

                # Render discovered companies table
                table = Table(title=f"Discovered Lookalike Companies (for {seed_domain})", show_header=True, header_style="bold cyan")
                table.add_column("#", justify="right", style="dim")
                table.add_column("Company Name", style="bold white")
                table.add_column("Domain", style="underline green")
                table.add_column("Country", style="magenta")
                table.add_column("Industries", style="yellow")
                
                for idx, comp in enumerate(companies):
                    industries_str = ", ".join(comp.industries[:3]) if comp.industries else "N/A"
                    table.add_row(
                        str(idx + 1),
                        comp.name or "N/A",
                        comp.domain or "N/A",
                        (comp.primary_country or "N/A").upper(),
                        industries_str
                    )
                console.print(table)
                rprint("\n")
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 403:
                    rprint("[bold red]Ocean.io plan does not permit this endpoint[/bold red]")
                    logger.warning("[Pipeline] Ocean.io returned 403 Forbidden. Plan does not permit this endpoint. Stopping gracefully.")
                    clear_checkpoint()
                    sys.exit(0)
                else:
                    logger.exception(f"[Pipeline] Stage 1 failed: {e}")
                    rprint("[bold red]CRITICAL: Stage 1 Ocean.io search failed. You can resume using --resume after fixing the issue.[/bold red]")
                    sys.exit(1)
            except Exception as e:
                logger.exception(f"[Pipeline] Stage 1 failed: {e}")
                rprint("[bold red]CRITICAL: Stage 1 Ocean.io search failed. You can resume using --resume after fixing the issue.[/bold red]")
                sys.exit(1)
    else:
        rprint(f"[bold green][OK] Stage 1 (Restored): Loaded {len(companies)} lookalike companies.[/bold green]")

    if not companies:
        rprint("[bold yellow]No lookalike companies found. Pipeline stopped.[/bold yellow]")
        generate_final_report(0, 0, 0, 0, 0, 0)
        clear_checkpoint()
        sys.exit(0)

    # ==========================================
    # STAGE 2: Prospeo Contact Discovery
    # ==========================================
    if start_stage <= 2:
        logger.info("[Pipeline] Starting Stage 2: Prospeo Contact Discovery")
        rprint("\n[bold cyan]Stage 2 Started...[/bold cyan]\n")
        
        # Sourcing contacts per company
        raw_contacts = []
        seen_linkedin = set()
        for idx, company in enumerate(companies):
            if prospeo_service.quota_depleted:
                rprint("\n[bold red]PROSPEO QUOTA EXHAUSTED[/bold red]")
                rprint("[bold red]Remaining Quota: 0[/bold red]")
                rprint("[bold red]Stopping Stage 2 to preserve resources.[/bold red]\n")
                break

            rprint(f"Scanning company: [bold white]{company.domain}[/bold white]")
            try:
                # Determine adaptive contacts limit based on remaining Prospeo quota
                contacts_limit = settings.PROSPEO_CONTACTS_LIMIT
                quota_left = prospeo_service.remaining_quota
                if quota_left is not None:
                    if quota_left < 5:
                        contacts_limit = 1
                        logger.info(f"[Pipeline] Adaptive limit: remaining quota < 5 ({quota_left}). Reducing company scan limit to 1.")
                    elif quota_left < 10:
                        contacts_limit = 3
                        logger.info(f"[Pipeline] Adaptive limit: remaining quota < 10 ({quota_left}). Reducing company scan limit to 3.")

                # Limit to contacts_limit contacts per company domain
                company_contacts = prospeo_service.find_contacts_for_company(
                    domain=company.domain,
                    company_name=company.name,
                    limit=contacts_limit
                )
                
                if prospeo_service.quota_depleted:
                    rprint("\n[bold red]PROSPEO QUOTA EXHAUSTED[/bold red]")
                    rprint("[bold red]Remaining Quota: 0[/bold red]")
                    rprint("[bold red]Stopping Stage 2 to preserve resources.[/bold red]\n")
                    break
                
                # Filter out duplicates and resolve emails immediately
                unique_company_contacts = []
                for contact in company_contacts:
                    lk_lower = contact.linkedin_url.lower()
                    if lk_lower in seen_linkedin:
                        continue
                    seen_linkedin.add(lk_lower)
                    
                    rprint(f"  Resolving email for {contact.full_name}...")
                    email = prospeo_service.resolve_email(
                        linkedin_url=contact.linkedin_url,
                        first_name=contact.first_name,
                        last_name=contact.last_name,
                        company_domain=contact.company_domain
                    )
                    contact.email = email
                    if email:
                        contact.email_status = "verified"
                    else:
                        contact.email_status = "unresolved"
                    unique_company_contacts.append(contact)
                    
                    if prospeo_service.quota_depleted:
                        break
                    
                raw_contacts.extend(unique_company_contacts)
                rprint(f"Found {len(unique_company_contacts)} unique decision makers for {company.domain}\n")
                
                if prospeo_service.quota_depleted:
                    rprint("\n[bold red]PROSPEO QUOTA EXHAUSTED[/bold red]")
                    rprint("[bold red]Remaining Quota: 0[/bold red]")
                    rprint("[bold red]Stopping Stage 2 to preserve resources.[/bold red]\n")
                    break
            except Exception as e:
                logger.error(f"[Pipeline] Sourcing failed for {company.domain}: {e}. Skipping company.")
                rprint("Found 0 decision makers\n")

        contacts = raw_contacts

        # Save Stage Output
        save_json(settings.STAGE2_CONTACTS_FILE, [c.to_dict() for c in contacts])
        save_checkpoint(seed_domain, 2)
        
        rprint("[bold green]Stage 2 Complete[/bold green]\n")
        
        # Display Prospeo Sourcing Statistics
        stats = prospeo_service.get_stats()
        rprint("[bold cyan]============================================================[/bold cyan]")
        rprint("[bold cyan]                 PROSPEO API STATISTICS                     [/bold cyan]")
        rprint("[bold cyan]============================================================[/bold cyan]")
        for key, val in stats.items():
            rprint(f"  {key:<24}: [bold green]{val}[/bold green]")
        rprint("[bold cyan]============================================================[/bold cyan]\n")

        rprint(f"[bold green]{len(contacts)} Unique Contacts Found[/bold green]\n")
        rprint("[bold green]Checkpoint Saved[/bold green]\n")
    else:
        rprint(f"[bold green][OK] Stage 2 (Restored): Loaded {len(contacts)} decision-makers.[/bold green]")

    if not contacts:
        rprint("[bold yellow]No decision-makers sourced. Pipeline stopped.[/bold yellow]")
        generate_final_report(len(companies), 0, 0, 0, 0, 0)
        clear_checkpoint()
        sys.exit(0)

    # ==========================================
    # SAFETY CHECKPOINT
    # ==========================================
    import os
    sender_email = os.getenv("SENDER_EMAIL") or settings.SENDER_EMAIL
    sender_name = os.getenv("SENDER_NAME") or settings.SENDER_NAME

    total_companies = len(companies)
    total_contacts = len(contacts)
    total_emails = sum(1 for c in contacts if c.email is not None and c.email != "")

    rprint("\n[bold cyan]============================================================[/bold cyan]")
    rprint("[bold cyan]                 SAFETY CHECKPOINT SUMMARY                  [/bold cyan]")
    rprint("[bold cyan]============================================================[/bold cyan]")
    rprint(f"  Sender Email     : [bold green]{sender_email}[/bold green]")
    rprint(f"  Total Companies  : [bold green]{total_companies}[/bold green]")
    rprint(f"  Total Contacts   : [bold green]{total_contacts}[/bold green]")
    rprint(f"  Total Emails     : [bold green]{total_emails}[/bold green]")
    rprint("[bold cyan]============================================================[/bold cyan]\n")

    # Prompt safety confirmation
    if args.dry_run:
        rprint("[bold yellow]--dry-run detected. Safety confirmation skipped; displaying campaign templates only.[/bold yellow]")
        proceed = True
    else:
        response = Prompt.ask(
            "[bold red]Do you want to send emails? (y/N)[/bold red]",
            default="n"
        ).strip().lower()
        proceed = response in ("y", "yes")

    if not proceed:
        rprint("[bold yellow]Outreach cancelled by user. State saved. Checkpoint cleared.[/bold yellow]")
        generate_final_report(total_companies, total_contacts, total_emails, 0, 0, total_contacts)
        clear_checkpoint()
        sys.exit(0)

    # Validate sender email (Requirement 8)
    if not settings.MOCK_MODE and (not os.getenv("SENDER_EMAIL") or os.getenv("SENDER_EMAIL").strip() == ""):
        rprint("[bold red]Sender email not configured[/bold red]")
        logger.warning("[Pipeline] Sender email not configured in environment. Stopping Stage 3 gracefully.")
        generate_final_report(total_companies, total_contacts, total_emails, 0, 0, total_contacts)
        clear_checkpoint()
        sys.exit(0)

    # ==========================================
    # STAGE 3: Brevo EMAIL DISPATCH
    # ==========================================
    logger.info("[Pipeline] Initiating Stage 3: Email Dispatch")
    sent_count = 0
    fail_count = 0
    skipped_count = 0
    email_records = []

    # Filter/personalize emails for all contacts
    for contact in contacts:
        if not contact.email:
            skipped_count += 1
            # Still track it in the campaign results as skipped
            record = EmailRecord(
                contact_name=contact.full_name,
                company_name=contact.company_name,
                recipient_email="",
                status="SKIPPED",
                error_message="Skipped: email = null"
            )
            email_records.append(record)
            continue

        record = EmailRecord(
            contact_name=contact.full_name,
            company_name=contact.company_name,
            recipient_email=contact.email
        )
        record.personalize(
            subject_template=settings.EMAIL_SUBJECT_TEMPLATE,
            body_template=settings.EMAIL_BODY_TEMPLATE,
            designation=contact.designation,
            sender_name=settings.SENDER_NAME
        )
        email_records.append(record)

    if args.dry_run:
        rprint("\n[bold yellow]>>> DRY RUN MODE: Displaying outreach copies without sending... <<<[/bold yellow]")
        for record in email_records:
            if record.status == "SKIPPED":
                continue
            log_content = (
                f"\n[bold green]To: {record.contact_name} <{record.recipient_email}> at {record.company_name}[/bold green]\n"
                f"Subject: {record.subject}\n"
                f"Body:\n{record.body}\n"
                f"[bold magenta]------------------------------------------------------------[/bold magenta]"
            )
            rprint(log_content)
            record.status = "SKIPPED"
            record.sent_at = datetime.now().isoformat()
            skipped_count += 1
        rprint("\n[bold yellow]>>> DRY RUN COMPLETE. No emails were actually sent. <<<[/bold yellow]")
    else:
        # Live/Mock Sending with batching & rate limit delays
        batch_size = settings.EMAIL_BATCH_SIZE
        delay_between = settings.EMAIL_DELAY_SECONDS
        delay_batch = settings.BATCH_DELAY_SECONDS
        
        valid_records = [r for r in email_records if r.status != "SKIPPED"]
        total_emails = len(valid_records)
        rprint(f"\n[cyan]Queued {total_emails} emails for dispatch. Batch Size: {batch_size}.[/cyan]")

        for i, record in enumerate(valid_records):
            # Batch boundaries
            if i > 0 and i % batch_size == 0:
                logger.info(f"[Pipeline] Reached batch size boundary ({batch_size}). Cooling down for {delay_batch}s...")
                with console.status(f"[bold yellow]Rate limit cooling down... Waiting {delay_batch}s[/bold yellow]", spinner="clock"):
                    time.sleep(delay_batch)

            # Individual email delay
            if i > 0 and i % batch_size != 0:
                time.sleep(delay_between)

            try:
                success = brevo_service.send_outreach_email(record)
                if success:
                    sent_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"[Pipeline] Exception during dispatch to {record.recipient_email}: {e}")
                record.status = "FAILED"
                record.error_message = str(e)
                fail_count += 1

    # ==========================================
    # REPORTING & CLEANUP
    # ==========================================
    # Save outreach records to data/emails.json
    save_json(settings.DATA_DIR / "emails.json", [r.to_dict() for r in email_records])
    
    # Save CSV Report
    csv_headers = ["Contact Name", "Company Name", "Email Address", "Subject", "Status", "Sent At", "Error Message"]
    csv_rows = [
        [r.contact_name, r.company_name, r.recipient_email, r.subject, r.status, r.sent_at or "", r.error_message or ""]
        for r in email_records
    ]
    save_csv(settings.FINAL_REPORT_FILE, csv_headers, csv_rows)

    # Save Pipeline JSON Report in project root
    generate_final_report(total_companies, total_contacts, total_emails, sent_count, fail_count, skipped_count)
    
    # Clear pipeline checkpoint upon successful termination
    clear_checkpoint()

    # Render Final Rich Status Table
    rprint("\n[bold cyan]============================================================[/bold cyan]")
    rprint("[bold cyan]                 PIPELINE RUN COMPLETE                      [/bold cyan]")
    rprint("[bold cyan]============================================================[/bold cyan]\n")
    
    summary_table = Table(title="Outreach Campaign Execution Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Metric", style="dim", width=30)
    summary_table.add_column("Count", justify="right", style="bold green")
    
    summary_table.add_row("Companies Sourced (Ocean.io)", str(total_companies))
    summary_table.add_row("Contacts Discovered (Prospeo)", str(total_contacts))
    summary_table.add_row("Emails Resolved (Prospeo)", str(total_emails))
    
    if args.dry_run:
        summary_table.add_row("Emails Dry Run (Skipped)", str(skipped_count), style="bold yellow")
    else:
        summary_table.add_row("Emails Dispatched Successfully", str(sent_count))
        summary_table.add_row("Email Dispatches Failed", str(fail_count), style="bold red" if fail_count > 0 else "green")
        summary_table.add_row("Emails Skipped (Null/dry run)", str(skipped_count), style="bold yellow" if skipped_count > 0 else "green")
        
    console.print(summary_table)
    rprint("\n")

if __name__ == "__main__":
    try:
        run_pipeline()
    except KeyboardInterrupt:
        rprint("\n[bold red]Pipeline interrupted by user. Exiting.[/bold red]")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"[Pipeline] Critical unhandled error: {e}")
        rprint(f"\n[bold red]Critical pipeline crash: {e}[/bold red]")
        sys.exit(1)
