"""Logging configuration for test purification."""

import logging

# Create logger
LOGGER = logging.getLogger("tcp")
LOGGER.setLevel(logging.INFO)


# Add handler to logger
def debug():
    LOGGER.setLevel(logging.DEBUG)
    for handler in LOGGER.handlers:
        handler.setLevel(logging.DEBUG)
