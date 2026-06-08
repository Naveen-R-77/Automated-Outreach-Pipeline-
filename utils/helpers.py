import csv
import json
import time
import random
import functools
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from utils.logger import logger
from config import settings

import requests

def retry_api(max_retries: int = 3, initial_delay: float = 2.0, backoff_factor: float = 2.0):
    """Decorator to retry network requests with exponential backoff and jitter."""
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check for non-retryable HTTP errors (like 401 Unauthorized or 403 Forbidden)
                    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                        if e.response.status_code in (401, 403):
                            logger.error(f"Non-retryable HTTP error {e.response.status_code} encountered. Bypassing retries.")
                            raise e

                    if attempt == max_retries:
                        logger.error(f"Failed '{func.__name__}' after {max_retries} attempts. Error: {e}")
                        raise e
                    
                    jitter = random.uniform(0.8, 1.2)
                    sleep_time = delay * jitter
                    logger.warning(
                        f"Attempt {attempt} for '{func.__name__}' failed: {e}. "
                        f"Retrying in {sleep_time:.2f} seconds..."
                    )
                    time.sleep(sleep_time)
                    delay *= backoff_factor
        return wrapper
    return decorator

def save_json(file_path: Path, data: Any) -> None:
    """Safely saves data to a JSON file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        logger.debug(f"Successfully saved JSON to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save JSON to {file_path}: {e}")
        raise e

def load_json(file_path: Path) -> Any:
    """Loads and parses a JSON file. Returns None if file does not exist."""
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON from {file_path}: {e}")
        raise e

def save_csv(file_path: Path, headers: List[str], rows: List[List[Any]]) -> None:
    """Exports structured data to a CSV file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        logger.debug(f"Successfully generated CSV report at [CSV]({file_path.as_uri()})")
    except Exception as e:
        logger.error(f"Failed to generate CSV report at {file_path}: {e}")
        raise e

# Checkpoint Management
def save_checkpoint(seed_domain: str, last_completed_stage: int) -> None:
    """Saves the current pipeline progress for recovery on failure."""
    checkpoint_data = {
        "seed_domain": seed_domain,
        "last_completed_stage": last_completed_stage,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    save_json(settings.CHECKPOINT_FILE, checkpoint_data)
    logger.debug(f"Checkpoint saved: Stage {last_completed_stage} completed for domain '{seed_domain}'")

def load_checkpoint() -> Optional[Dict[str, Any]]:
    """Loads checkpoint data if it exists and is valid."""
    data = load_json(settings.CHECKPOINT_FILE)
    if data:
        logger.debug(f"Checkpoint found: Stage {data['last_completed_stage']} completed for '{data['seed_domain']}'")
        return data
    return None

def clear_checkpoint() -> None:
    """Removes the checkpoint file to reset pipeline state."""
    if settings.CHECKPOINT_FILE.exists():
        settings.CHECKPOINT_FILE.unlink()
        logger.debug("Checkpoint file cleared.")
