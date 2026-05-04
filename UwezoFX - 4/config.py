# config.py
import os
import json
from dotenv import load_dotenv
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from modules.utils.helpers import resource_path, writable_path

load_dotenv(resource_path('.env'))

class Settings:
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    BREVO_API_KEY = os.getenv('BREVO_API_KEY')
    FROM_EMAIL = os.getenv('FROM_EMAIL')
    AT_USERNAME = os.getenv('AT_USERNAME')
    AT_API_KEY = os.getenv('AT_API_KEY')
    ADMIN_PHONE = os.getenv('ADMIN_PHONE')
    MYFXBOOK_EMAIL = os.getenv('MYFXBOOK_EMAIL')
    MYFXBOOK_PASSWORD = os.getenv('MYFXBOOK_PASSWORD')

@dataclass
class TradingConfig:
    """Complete trading configuration – ENHANCED REVERSAL EDITION"""
    
    # Basic settings
    symbol: Optional[str] = None
    magic_number: int = 202401
    slippage: int = 20
    reversal_mode: bool = False
    auto_trading: bool = False

    # Security settings
    idle_timeout_minutes: int = 10

    # Database settings
    database_file: str = "trading_users.db"

    # Profile photo settings
    profile_photo_folder: str = "profile_photos"

    # Trade limiting - FIXED to 5 trades and 5 orders per session
    min_trades_per_signal: int = 5
    max_trades_per_session: int = 5
    trades_taken_current_session: int = 0
    trades_taken_current_signal: int = 0
    max_concurrent_positions: int = 5
    aggressive_mode_positions: int = 5

    # Pending order management
    pending_order_timeout_seconds: int = 300   # Cancel orders older than 5 minutes
    pending_order_check_interval: int = 60     # Check every minute

    # Position sizing
    position_sizing_method: str = "fixed"
    risk_per_trade: float = 0.02
    fixed_lot_size: float = 0.01
    max_position_size: float = 1.0
    min_position_size: float = 0.01

    auto_trade_lot_size: Optional[float] = None

    # Risk management - PIPS instead of dollars
    max_daily_loss_percent: float = 20.0
    max_drawdown: float = 20.0
    max_consecutive_losses: int = 5
    stop_loss_pips: float = 50.0
    take_profit_pips: float = 100.0
    enable_stop_loss: bool = True
    enable_take_profit: bool = True
    close_opposite_on_signal_change: bool = False

    # Trading hours
    trading_start_hour: int = 0
    trading_end_hour: int = 23

    # Aggressive trading
    aggressive_trade_interval: int = 30
    normal_trade_interval: int = 60
    aggressive_trades_per_minute: int = 2

    # Indicator thresholds
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    cci_overbought: float = 100.0
    cci_oversold: float = -100.0
    williams_overbought: float = -20.0
    williams_oversold: float = -80.0
    require_all_timeframes_aligned: bool = False
    timeframe_weights: Dict[str, float] = field(default_factory=lambda: {
        "D1": 1.0, "H4": 0.8, "H1": 0.6, "M15": 0.4, "M5": 0.2
    })

    # Logging
    log_level: str = "INFO"
    log_file: str = "trading_system.log"

    # Trailing Stop-Loss (Step Trailing)
    enable_trailing_stop_loss: bool = False
    lock_amount_dollars: float = 3.0
    step_amount_dollars: float = 4.0

    # Short Time Signal (STS)
    use_sts_signal: bool = False

    # ICT/SMS Indicator Settings (Normal)
    normal_length: int = 5
    normal_atr_period: int = 14
    normal_momentum_threshold_base: float = 0.01

    # ICT/SMS Indicator Settings (STS)
    sts_length: int = 3
    sts_atr_period: int = 7
    sts_momentum_threshold_base: float = 0.02

    # Shared indicator settings
    use_ict_mss: bool = True
    use_ict_bos: bool = True
    use_ict_fvg: bool = True
    use_ict_ob: bool = True
    use_ict_vi: bool = True
    use_ict_displacement: bool = False
    use_sms_momentum_filter: bool = True
    use_sms_trend_filter: bool = True
    use_sms_volume_filter: bool = True
    use_sms_breakout_filter: bool = True
    use_sms_divergence: bool = True
    require_fvg_confirmation: bool = False
    require_ob_confirmation: bool = False
    sms_pre_momentum_factor: float = 0.5
    rsi_period: int = 14
    cci_period: int = 20
    williams_period: int = 14
    sms_volume_long_period: int = 50
    sms_volume_short_period: int = 5
    sms_breakout_period: int = 5
    max_vi: int = 2
    max_fvg: int = 5
    max_obs: int = 10
    max_swing_points: int = 50
    fvg_type: str = 'FVG'
    use_body_for_ob: bool = True
    min_signal_distance: int = 5

    # STS independent signals
    use_sts_1min: bool = True
    use_sts_5min: bool = True
    sts_1min_weight: float = 0.5
    sts_5min_weight: float = 0.5
    sts_alignment_threshold: float = 0.2

    # Weighted Vote Settings
    weight_5min: float = 0.7
    weight_15min: float = 0.3
    alignment_threshold: float = 0.3

    # News Settings (now use env)
    myfxbook_email: str = Settings.MYFXBOOK_EMAIL or ""
    myfxbook_password: str = Settings.MYFXBOOK_PASSWORD or ""
    use_news_sentiment: bool = False

    # Cache settings
    cache_enabled: bool = True
    cache_ttl: int = 300
    cache_dir: str = "cache"
    
    # ============================================================
    # ENHANCED REVERSAL TRADING CONFIGURATION - 10 CONFIRMATIONS
    # ============================================================
    # Master switch
    enable_reversal_trading: bool = False
    reversal_max_trades: int = 5
    reversal_cooldown_seconds: int = 300
    reversal_trade_volume: float = 0.01
    reversal_use_dynamic_sl: bool = True
    reversal_max_sl_pips: float = 80.0
    reversal_min_sl_pips: float = 30.0
    
    # 1. PRICE CONFIRMATION
    reversal_require_retest: bool = True
    reversal_retest_wait_seconds: int = 5
    reversal_retest_tolerance_pips: float = 10.0
    reversal_require_confirmation_candle: bool = True
    reversal_confirmation_candle_body_percent: float = 60.0
    reversal_max_price_move_pips: float = 0
    
    # 2. VOLATILITY FILTER
    reversal_use_volatility_filter: bool = True
    reversal_max_atr_percent: float = 2.0
    reversal_min_atr_percent: float = 0.3
    reversal_volatility_lookback: int = 14
    
    # 3. VOLUME CONFIRMATION
    reversal_require_volume_spike: bool = True
    reversal_volume_multiplier: float = 1.5
    reversal_volume_lookback: int = 20
    
    # 4. MOMENTUM FILTER
    reversal_use_momentum_filter: bool = True
    reversal_momentum_period: int = 5
    reversal_min_momentum_pips: float = 5.0
    
    # 5. SUPPORT/RESISTANCE
    reversal_check_support_resistance: bool = True
    reversal_sr_lookback_bars: int = 50
    reversal_sr_tolerance_pips: float = 15.0
    
    # 6. NEWS FILTER
    reversal_avoid_high_impact_news: bool = True
    reversal_news_buffer_minutes: int = 30
    
    # 7. TIME FILTER
    reversal_use_time_filter: bool = True
    reversal_preferred_hours_start: int = 8
    reversal_preferred_hours_end: int = 16
    reversal_avoid_london_close: bool = True
    reversal_avoid_friday_afternoon: bool = True
    
    # 8. MULTI-TIMEFRAME CONFIRMATION
    reversal_require_higher_tf_alignment: bool = True
    reversal_higher_tf: str = "H1"
    reversal_trend_alignment_percent: float = 70.0
    
    # 9. PATTERN CONFIRMATION
    reversal_require_pattern: bool = True
    reversal_valid_patterns: List[str] = field(default_factory=lambda: [
        "PIN_BAR", "ENGULFING", "MORNING_STAR", "EVENING_STAR", 
        "HAMMER", "SHOOTING_STAR", "INSIDE_BAR"
    ])
    
    # 10. FIBONACCI CONFIRMATION
    reversal_use_fibonacci: bool = True
    reversal_fib_levels: List[float] = field(default_factory=lambda: [0.382, 0.5, 0.618])
    reversal_fib_tolerance_pips: float = 5.0
    
    # 11. TRENDLINE & SUPPORT/RESISTANCE CONFIRMATION (NEW)
    reversal_use_trendline_sr: bool = True
    reversal_trendline_min_strength: int = 2
    reversal_confluence_zone_width: float = 0.01
    
    # Confidence threshold (minimum % of conditions that must be met)
    reversal_min_confidence_score: float = 30.0

    def save(self, filepath: str = "trading_config.json"):
        filepath = writable_path(filepath)
        with open(filepath, 'w') as f:
            json.dump(asdict(self), f, indent=4)

    @classmethod
    def load(cls, filepath: str = "trading_config.json"):
        filepath = resource_path(filepath)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            data.pop('reversal_stop_loss_pips', None)
            data.pop('reversal_take_profit_pips', None)
            return cls(**data)
        return cls()

    