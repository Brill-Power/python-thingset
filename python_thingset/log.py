
import logging
import sys

def get_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger
