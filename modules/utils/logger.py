# modules/utils/logger.py
import logging
import sys
from modules.utils.helpers import resource_path

def setup_logger(name="UWEZO_DERIV", log_level=logging.INFO, log_file="deriv_bot.log"):
    log_file = resource_path(log_file)
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    return logger