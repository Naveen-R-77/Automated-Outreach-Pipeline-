import logging
import sys
from rich.logging import RichHandler
from config import settings

def setup_logger(name: str = "pipeline") -> logging.Logger:
    """Configures a logger that writes info/debug messages to both console (colorized) and logs/pipeline.log."""
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 1. Console Rich Handler (info and above)
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_path=False
    )
    if settings.DEBUG_MODE:
        console_handler.setLevel(logging.DEBUG)
    else:
        console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. File Handler (all logs including debug)
    # Ensure directory exists just in case
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file_path = settings.LOG_DIR / "pipeline.log"
    
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

# Export a default instance
logger = setup_logger()
