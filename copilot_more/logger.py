import os
import sys

from loguru import logger

from copilot_more.settings import settings

# Get log level from environment, default to INFO if not set
log_level = os.environ.get("LOGURU_LEVEL", None) or settings.loguru_level or "INFO"

# Configure logger with the determined level
logger.remove()  # Remove default handlers
logger.add(sink=sys.stderr, level=log_level)  # Add handler with specified level

# Export the configured logger
__all__ = ["logger"]
