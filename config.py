# config.py
import os
import json
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional, Dict, List

load_dotenv()

class Settings:
    """Global settings from environment"""
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    BREVO_API_KEY = os.getenv('BREVO_API_KEY')
    FROM_EMAIL = os.getenv('FROM_EMAIL')
    AT_USERNAME = os.getenv('AT_USERNAME')
    AT_API_KEY = os.getenv('AT_API_KEY')
    ADMIN_PHONE = os.getenv('ADMIN_PHONE')
    DERIV_APP_ID = int(os.getenv('DERIV_APP_ID', 133059))

@dataclass
class BotConfig:
    """Trading bot configuration"""
    app_id: int = Settings.DERIV_APP_ID
    symbol: str = "R_100"
    granularity_seconds: int = 60
    base_stake: float = 1.0
    duration: int = 1
    ticks_duration: int = 5
    auto_ticks: bool = False
    cooldown: int = 60
    max_daily_loss: float = 50.0
    martingale_mult: float = 2.5
    max_martingale_steps: int = 4
    martingale_mode: str = "Classic"
    confirmations_required: int = 2
    selected_strategy: str = "ICT/SMS"
    timeframe: str = "1m"
    auto_trade: bool = False
    adaptive_mode: bool = False
    min_digit_edge: float = 8.0
    min_digit_confidence: int = 68
    
    
    def save(self, filepath: str = "bot_config.json"):
        with open(filepath, 'w') as f:
            json.dump(self.__dict__, f, indent=4)
    
    @classmethod
    def load(cls, filepath: str = "bot_config.json"):
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            return cls(**data)
        return cls()
