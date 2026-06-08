from abc import ABC
from utils.logger import logger
from config import settings

class BaseService(ABC):
    """Abstract Base Service handling logging, mock-mode configurations, and standard API states."""
    
    def __init__(self, service_name: str, api_key: str, mock_mode: bool = False):
        self.service_name = service_name
        self.api_key = api_key.strip() if api_key else ""
        
        # Decide if the service should run in Simulation (Mock) Mode:
        # Mock mode should only activate when python main.py --mock is explicitly provided.
        self.mock_mode = settings.MOCK_MODE
        
        self.logger = logger
        
        if self.mock_mode:
            self.logger.debug(
                f"[{self.service_name}] Initialized in DEVELOPMENT/SIMULATION MODE. "
                "No live API requests will be performed."
            )
        else:
            self.logger.debug(f"[{self.service_name}] Initialized in PRODUCTION LIVE MODE.")
            
    def validate_credentials(self) -> bool:
        """Helper to ensure API keys are configured for live requests."""
        if not self.mock_mode and not self.api_key:
            self.logger.error(f"[{self.service_name}] Missing API Key! Configure it in your .env file or run with --mock.")
            return False
        return True
