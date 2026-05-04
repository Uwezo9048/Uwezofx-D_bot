import logging
import sys
from modules.utils.helpers import writable_path   # <-- ADD THIS IMPORT

def setup_logger(name="UWEZO_FX", log_level=logging.INFO, log_file="trading_system.log"):
    log_file = writable_path(log_file)   # <-- ADD THIS LINE
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger




"""
# modules/utils/logger.py
import logging
import sys
import io


def setup_logger(name="UWEZO_FX", log_level=logging.INFO, log_file="trading_system.log"):
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8'))
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

    return logger
"""