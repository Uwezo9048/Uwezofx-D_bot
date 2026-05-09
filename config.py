# config.py
import os
import json
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Union

load_dotenv()

DEFAULT_DERIV_PAT_APP_ID = "33cqkvVDkguOv3GBkC6OU"
DEFAULT_DERIV_OAUTH_APP_ID = "33cpZRDi4o4dXSLamujEv"
DEFAULT_DERIV_LEGACY_APP_ID = "133059"


def _clean_env(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


def _pat_app_id_from_env() -> str:
    explicit_pat_app_id = _clean_env("DERIV_PAT_APP_ID")
    if explicit_pat_app_id:
        return explicit_pat_app_id

    legacy_name_app_id = _clean_env("DERIV_APP_ID")
    if legacy_name_app_id and not legacy_name_app_id.isdigit():
        return legacy_name_app_id

    return DEFAULT_DERIV_PAT_APP_ID


class Settings:
    """Global settings from environment"""
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    BREVO_API_KEY = os.getenv('BREVO_API_KEY')
    FROM_EMAIL = os.getenv('FROM_EMAIL')
    AT_USERNAME = os.getenv('AT_USERNAME')
    AT_API_KEY = os.getenv('AT_API_KEY')
    ADMIN_PHONE = os.getenv('ADMIN_PHONE')
    DERIV_PAT_APP_ID = _pat_app_id_from_env()
    DERIV_OAUTH_APP_ID = _clean_env('DERIV_OAUTH_APP_ID', DEFAULT_DERIV_OAUTH_APP_ID)
    DERIV_LEGACY_APP_ID = _clean_env('DERIV_LEGACY_APP_ID', DEFAULT_DERIV_LEGACY_APP_ID)
    DERIV_APP_ID = DERIV_PAT_APP_ID

@dataclass
class BotConfig:
    """Trading bot configuration"""
    app_id: Union[str, int] = Settings.DERIV_APP_ID
    symbol: str = "R_100"
    granularity_seconds: int = 60
    base_stake: float = 1.0
    duration: int = 1
    ticks_duration: int = 5
    auto_ticks: bool = False
    cooldown: int = 60
    max_daily_loss: float = 50.0
    max_daily_profit: float = 0.0
    martingale_mult: float = 2.5
    max_martingale_steps: int = 4
    martingale_mode: str = "Classic"
    confirmations_required: int = 2
    selected_strategy: str = "ICT/SMS"
    timeframe: str = "1m"
    deriv_account: str = ""
    user_timezone: str = ""
    auto_trade: bool = False
    adaptive_mode: bool = False
    adaptive_enabled: bool = False
    adaptive_pair: str = "Over/Under"
    min_digit_edge: float = 8.0
    min_digit_confidence: int = 65
    confidence_ladder: str = "75/80/85"
    
    
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
