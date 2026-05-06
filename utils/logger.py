"""
Centralized logging utility for CareerAgent.
Ensures all errors are captured with full stack traces and formatted appropriately.
"""
import logging
import sys
import os

def setup_logger(name: str) -> logging.Logger:
    """
    Sets up a logger with console output and proper formatting.
    Includes full stack traces for exceptions.
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if already configured
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

def get_logger(name: str) -> logging.Logger:
    return setup_logger(name)
