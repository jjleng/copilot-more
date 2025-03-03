import os
import sys
from typing import Optional

from loguru import logger

# Initialize with default level
DEFAULT_LOG_LEVEL = "INFO"
logger.remove()  # Remove default handlers
logger.add(sink=sys.stderr, level=DEFAULT_LOG_LEVEL)


def init_logger(log_level: Optional[str] = None):
    """Initialize logger with specified level or from environment."""
    # Get log level from environment or use provided level, fallback to default
    level = log_level or os.environ.get("LOGURU_LEVEL", DEFAULT_LOG_LEVEL)

    # Reconfigure logger with new level
    logger.remove()  # Remove existing handlers
    assert level
    logger.add(sink=sys.stderr, level=level)


# Export the logger
__all__ = ["logger", "init_logger"]
