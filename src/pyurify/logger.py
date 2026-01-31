"""
Logging Configuration for Test Purification

This module configures logging for the Pyurify package.
"""

import logging

# Configure the logger
LOGGER = logging.getLogger("pyurify")
LOGGER.setLevel(logging.INFO)


def debug():
    """
    Enable debug-level logging for the Pyurify logger.

    This function sets the logging level to DEBUG for both the logger and its handlers,
    allowing detailed debug information to be displayed.
    """
    # Set the logger level to DEBUG
    LOGGER.setLevel(logging.DEBUG)
    # Set the level for all handlers to DEBUG
    for handler in LOGGER.handlers:
        handler.setLevel(logging.DEBUG)
