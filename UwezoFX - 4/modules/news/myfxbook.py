# modules/news/myfxbook.py
import time
import datetime
from typing import List, Dict, Optional
import requests
from config import Settings

# Try to import myfxbook
try:
    import myfxbook
    MYFXBOOK_AVAILABLE = True
except ImportError:
    MYFXBOOK_AVAILABLE = False

class MyfxbookNewsManager:
    MAJOR_ASSETS = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
        'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'CADJPY', 'CHFJPY', 'NZDJPY',
        'XAUUSD', 'XAGUSD', 'USOIL', 'BTCUSD', 'ETHUSD',
        'SP500', 'US30', 'NAS100', 'DAX30', 'FTSE100', 'UK100'
    ]
    
    MAJOR_CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD', 'NZD', 'CNY']
    
    PAIR_MAP = {
        'USD': ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'],
        'EUR': ['EURUSD', 'EURGBP', 'EURJPY', 'EURCHF', 'EURCAD', 'EURAUD', 'EURNZD'],
        'GBP': ['GBPUSD', 'EURGBP', 'GBPJPY', 'GBPCHF', 'GBPCAD', 'GBPAUD', 'GBPNZD'],
        'JPY': ['USDJPY', 'EURJPY', 'GBPJPY', 'CHFJPY', 'CADJPY', 'AUDJPY', 'NZDJPY'],
        'CHF': ['USDCHF', 'EURCHF', 'GBPCHF', 'CHFJPY'],
        'CAD': ['USDCAD', 'EURCAD', 'GBPCAD', 'CADJPY'],
        'AUD': ['AUDUSD', 'EURAUD', 'GBPAUD', 'AUDJPY', 'AUDCAD', 'AUDCHF', 'AUDNZD'],
        'NZD': ['NZDUSD', 'EURNZD', 'GBPNZD', 'NZDJPY', 'NZDCAD', 'NZDCHF', 'AUDNZD'],
        'XAU': ['XAUUSD', 'XAUEUR', 'XAUGBP', 'XAUJPY'],
        'XAG': ['XAGUSD'],
        'OIL': ['USOIL', 'UKOIL'],
        'BTC': ['BTCUSD'],
        'ETH': ['ETHUSD'],
    }
    
    def __init__(self, config, logger, callback_queue):
        self.config = config
        self.logger = logger
        self.callback_queue = callback_queue
        
        self.api_client = None
        self.api_available = MYFXBOOK_AVAILABLE
        self.is_logged_in = False
        self.session_id = None
        self.last_login_time = None
        
        self.news_cache = []
        self.last_fetch = None
        self.cache_duration = 300
        
        self.market_sentiment = {}
        
        # Use credentials from Settings
        self.myfxbook_email = Settings.MYFXBOOK_EMAIL
        self.myfxbook_password = Settings.MYFXBOOK_PASSWORD
        
        self.logger.info(f"Myfxbook credentials - Email: {'Set' if self.myfxbook_email else 'Not set'}, Password: {'Set' if self.myfxbook_password else 'Not set'}")
        self.logger.info(f"Myfxbook package available: {MYFXBOOK_AVAILABLE}")
        
        if self.api_available and self.myfxbook_email and self.myfxbook_password:
            self.logger.info("Attempting to initialize Myfxbook API...")
            self._init_api()
        else:
            self.logger.warning("Myfxbook API not initialized - missing credentials or package")

    def _init_api(self):
        try:
            self.logger.info(f"Creating myfxbook client with email: {self.myfxbook_email[:3]}...")
            self.api_client = myfxbook.Myfxbook(
                self.myfxbook_email, 
                self.myfxbook_password
            )
            self.logger.info("✅ Myfxbook API client object created successfully")
            self.login()
        except ImportError as e:
            self.logger.error(f"❌ Import error: {e}. Make sure myfxbook is installed: pip install myfxbook")
            self.api_available = False
        except Exception as e:
            self.logger.error(f"Failed to initialize Myfxbook API: {e}")
            self.api_available = False
    
    def login(self) -> bool:
        if not self.api_available or not self.api_client:
            self.logger.warning("Myfxbook API not available, using fallback data")
            return False
        try:
            self.logger.info(f"Attempting to login to Myfxbook as {self.myfxbook_email}...")
            result = self.api_client.login()
            self.logger.info(f"Login result type: {type(result)}")
            self.logger.info(f"Login result: {result}")
            if result and isinstance(result, dict):
                if result.get('error') == False:
                    self.is_logged_in = True
                    self.session_id = result.get('session')
                    self.last_login_time = datetime.datetime.now()
                    self.logger.info("✅ SUCCESSFULLY logged into Myfxbook!")
                    self.logger.info(f"Session ID: {self.session_id[:10]}...")
                    return True
                else:
                    error_msg = result.get('message', 'Unknown error')
                    self.logger.error(f"❌ Myfxbook login failed: {error_msg}")
                    return False
            else:
                self.logger.error(f"❌ Unexpected login response format: {result}")
                return False
        except AttributeError as e:
            self.logger.error(f"❌ AttributeError - Myfxbook API might have changed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ Error logging into Myfxbook: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def logout(self):
        if not self.api_available or not self.api_client:
            return
        try:
            if self.is_logged_in:
                self.api_client.logout()
                self.is_logged_in = False
                self.session_id = None
                self.logger.info("Logged out from Myfxbook")
        except Exception as e:
            self.logger.error(f"Error logging out from Myfxbook: {e}")
    
    def ensure_login(self) -> bool:
        if not self.api_available:
            return False
        if not self.is_logged_in:
            return self.login()
        if self.last_login_time and (datetime.datetime.now() - self.last_login_time).seconds > 1200:
            self.logger.info("Session expired, re-logging in...")
            return self.login()
        return True
    
    def fetch_news(self, force_refresh: bool = False) -> List[Dict]:
        now = datetime.datetime.now()
        if not force_refresh and self.last_fetch and (now - self.last_fetch).seconds < self.cache_duration:
            self.logger.info("Using cached news data")
            return self.news_cache
        self.logger.info(f"Fetching news - API available: {self.api_available}, Logged in: {self.is_logged_in}")
        if self.api_available:
            self.logger.info("Attempting to fetch from Myfxbook API...")
            news = self._fetch_from_api()
            if news:
                self.logger.info(f"✅ Successfully fetched {len(news)} news items from API")
                self.news_cache = news
                self.last_fetch = now
                return news
            else:
                self.logger.warning("API fetch returned no data, using fallback")
        self.logger.info("Using fallback news generation")
        news = self._generate_fallback_news()
        self.news_cache = news
        self.last_fetch = now
        return news
    
    def _fetch_from_api(self) -> Optional[List[Dict]]:
        if not self.ensure_login():
            self.logger.warning("Could not ensure login, skipping API fetch")
            return None
        try:
            self.logger.info("Calling get_calendar()...")
            result = self.api_client.get_calendar()
            self.logger.info(f"Calendar result type: {type(result)}")
            if result and isinstance(result, dict):
                if result.get('error') == False:
                    events = result.get('calendar', [])
                    self.logger.info(f"Raw events count: {len(events)}")
                    processed_events = []
                    for event in events:
                        currency = event.get('country', '')
                        if self._is_major_asset(currency):
                            processed = self._enhance_event(event)
                            processed_events.append(processed)
                    self.logger.info(f"✅ Processed {len(processed_events)} news items from Myfxbook API")
                    return processed_events
                else:
                    error_msg = result.get('message', 'Unknown error')
                    self.logger.error(f"❌ API calendar fetch failed: {error_msg}")
                    return None
            else:
                self.logger.error(f"❌ Unexpected calendar response format: {result}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Error fetching from API: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _is_major_asset(self, currency: str) -> bool:
        if currency in self.MAJOR_CURRENCIES:
            return True
        for asset in self.MAJOR_ASSETS:
            if currency in asset:
                return True
        return False
    
    def _enhance_event(self, event: Dict) -> Dict:
        event['sentiment'] = self._analyze_sentiment(event)
        event['prediction'] = self._generate_prediction(event)
        event['trading_signals'] = self._generate_signals(event)
        event.setdefault('time', '00:00')
        event.setdefault('date', datetime.datetime.now().strftime('%Y-%m-%d'))
        event.setdefault('impact', 'Medium')
        event.setdefault('forecast', 'N/A')
        event.setdefault('previous', 'N/A')
        event.setdefault('actual', 'N/A')
        return event
    
    def _analyze_sentiment(self, event: Dict) -> Dict:
        try:
            impact = event.get('impact', '').lower()
            actual = event.get('actual')
            forecast = event.get('forecast')
            previous = event.get('previous')
            sentiment_score = 0.0
            confidence = "LOW"
            if impact == 'high':
                sentiment_score = 0.3
                confidence = "MEDIUM"
            elif impact == 'medium':
                sentiment_score = 0.2
                confidence = "LOW"
            if actual and forecast and actual != 'N/A' and forecast != 'N/A':
                try:
                    actual_val = float(actual)
                    forecast_val = float(forecast)
                    if actual_val > forecast_val:
                        sentiment_score += 0.4
                        confidence = "HIGH"
                    elif actual_val < forecast_val:
                        sentiment_score -= 0.4
                        confidence = "HIGH"
                except (ValueError, TypeError):
                    pass
            sentiment_score = max(-1.0, min(1.0, sentiment_score))
            if sentiment_score >= 0.6:
                label = "STRONG_BULLISH"
            elif sentiment_score >= 0.2:
                label = "BULLISH"
            elif sentiment_score <= -0.6:
                label = "STRONG_BEARISH"
            elif sentiment_score <= -0.2:
                label = "BEARISH"
            else:
                label = "NEUTRAL"
            return {
                'score': round(sentiment_score, 2),
                'label': label,
                'confidence': confidence,
            }
        except Exception as e:
            self.logger.error(f"Sentiment analysis error: {e}")
            return {'score': 0.0, 'label': 'NEUTRAL', 'confidence': 'LOW'}
    
    def _generate_prediction(self, event: Dict) -> Dict:
        sentiment = event.get('sentiment', {})
        impact = event.get('impact', '').lower()
        expected_pips = 0
        confidence = "LOW"
        if impact == 'high':
            expected_pips = 50
            confidence = "MEDIUM"
        elif impact == 'medium':
            expected_pips = 25
            confidence = "LOW"
        else:
            expected_pips = 10
            confidence = "LOW"
        sentiment_label = sentiment.get('label', 'NEUTRAL')
        if sentiment_label in ['STRONG_BULLISH', 'STRONG_BEARISH']:
            expected_pips = int(expected_pips * 1.5)
            confidence = "HIGH"
        elif sentiment_label in ['BULLISH', 'BEARISH']:
            expected_pips = int(expected_pips * 1.2)
            confidence = "MEDIUM" if confidence == "LOW" else confidence
        sentiment_score = sentiment.get('score', 0)
        if sentiment_score >= 0.2:
            direction = "UP"
        elif sentiment_score <= -0.2:
            direction = "DOWN"
        else:
            direction = "VOLATILE"
        return {
            'direction': direction,
            'expected_pips': expected_pips,
            'confidence': confidence,
            'timeframe': '15-30 minutes after release'
        }
    
    def _generate_signals(self, event: Dict) -> List[Dict]:
        currency = event.get('country', '')
        sentiment = event.get('sentiment', {})
        impact = event.get('impact', '').lower()
        affected_pairs = self.PAIR_MAP.get(currency, [])
        signals = []
        sentiment_score = sentiment.get('score', 0)
        confidence = sentiment.get('confidence', 'LOW')
        for pair in affected_pairs:
            if pair not in self.MAJOR_ASSETS:
                continue
            if sentiment_score >= 0.3:
                if pair.startswith(currency):
                    signal = "BUY"
                elif pair.endswith(currency):
                    signal = "SELL"
                else:
                    signal = "NEUTRAL"
            elif sentiment_score <= -0.3:
                if pair.startswith(currency):
                    signal = "SELL"
                elif pair.endswith(currency):
                    signal = "BUY"
                else:
                    signal = "NEUTRAL"
            else:
                signal = "NEUTRAL"
            base_sl = 50 if impact == 'high' else 30 if impact == 'medium' else 20
            base_tp = base_sl * 2
            signals.append({
                'pair': pair,
                'signal': signal,
                'strength': impact.upper(),
                'confidence': confidence,
                'entry_strategy': "Wait for 5min candle close after news",
                'stop_loss': f"{base_sl} pips",
                'take_profit': f"{base_tp} pips",
                'sentiment_score': sentiment_score
            })
        return signals
    
    def _generate_fallback_news(self) -> List[Dict]:
        now = datetime.datetime.now()
        news = []
        base_events = [
            {
                'country': 'USD',
                'event': 'Federal Reserve Interest Rate Decision',
                'impact': 'High',
                'time': '14:00',
                'forecast': '5.50%',
                'previous': '5.50%',
            },
            {
                'country': 'EUR',
                'event': 'ECB Monetary Policy Statement',
                'impact': 'High',
                'time': '13:45',
                'forecast': '4.00%',
                'previous': '4.00%',
            },
            {
                'country': 'GBP',
                'event': 'Bank of England Interest Rate Decision',
                'impact': 'High',
                'time': '12:00',
                'forecast': '5.25%',
                'previous': '5.25%',
            },
            {
                'country': 'JPY',
                'event': 'BoJ Interest Rate Decision',
                'impact': 'High',
                'time': '03:00',
                'forecast': '-0.10%',
                'previous': '-0.10%',
            },
            {
                'country': 'USD',
                'event': 'Non-Farm Employment Change',
                'impact': 'High',
                'time': '13:30',
                'forecast': '180K',
                'previous': '175K',
            },
            {
                'country': 'USD',
                'event': 'CPI Inflation Rate YoY',
                'impact': 'High',
                'time': '13:30',
                'forecast': '3.2%',
                'previous': '3.1%',
            },
            {
                'country': 'XAU',
                'event': 'Gold Prices',
                'impact': 'Medium',
                'time': '15:00',
                'forecast': '2000',
                'previous': '1980',
            },
            {
                'country': 'OIL',
                'event': 'Crude Oil Inventories',
                'impact': 'Medium',
                'time': '15:30',
                'forecast': '-2.5M',
                'previous': '-2.3M',
            }
        ]
        for event in base_events:
            enhanced = self._enhance_event(event)
            enhanced['date'] = now.strftime('%Y-%m-%d')
            news.append(enhanced)
        news.sort(key=lambda x: x['time'])
        return news
    
    def get_market_sentiment(self) -> Dict:
        news = self.fetch_news()
        total_score = 0
        high_impact_count = 0
        medium_impact_count = 0
        bullish_count = 0
        bearish_count = 0
        for event in news:
            sentiment = event.get('sentiment', {})
            score = sentiment.get('score', 0)
            impact = event.get('impact', '').lower()
            if impact == 'high':
                total_score += score * 2
                high_impact_count += 1
            elif impact == 'medium':
                total_score += score
                medium_impact_count += 1
            label = sentiment.get('label', 'NEUTRAL')
            if label in ['BULLISH', 'STRONG_BULLISH']:
                bullish_count += 1
            elif label in ['BEARISH', 'STRONG_BEARISH']:
                bearish_count += 1
        total_events = len(news)
        avg_score = total_score / max(total_events, 1)
        if avg_score >= 0.3:
            mood = "BULLISH"
        elif avg_score <= -0.3:
            mood = "BEARISH"
        else:
            mood = "NEUTRAL"
        if high_impact_count >= 3:
            confidence = "HIGH"
        elif high_impact_count >= 1:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        sentiment_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'overall_sentiment': mood,
            'sentiment_score': round(avg_score, 2),
            'high_impact_events': high_impact_count,
            'medium_impact_events': medium_impact_count,
            'total_events': total_events,
            'bullish_events': bullish_count,
            'bearish_events': bearish_count,
            'confidence': confidence,
        }
        self.market_sentiment = sentiment_data
        return sentiment_data
    
    def get_sentiment_score(self) -> float:
        sentiment = self.get_market_sentiment()
        return sentiment.get('sentiment_score', 0.0)
    
    def get_trading_recommendations(self) -> List[Dict]:
        recommendations = []
        news = self.fetch_news()
        for event in news:
            if event.get('impact') in ['High', 'Medium']:
                for signal in event.get('trading_signals', []):
                    if signal['signal'] != 'NEUTRAL':
                        recommendations.append({
                            'pair': signal['pair'],
                            'signal': signal['signal'],
                            'strength': signal['strength'],
                            'confidence': signal['confidence'],
                            'event': event['event'],
                            'time': event['time'],
                            'country': event['country'],
                            'entry_strategy': signal['entry_strategy'],
                            'stop_loss': signal['stop_loss'],
                            'take_profit': signal['take_profit'],
                            'sentiment_score': signal.get('sentiment_score', 0)
                        })
        def sort_key(rec):
            score = 0
            if rec['confidence'] == 'HIGH':
                score += 3
            elif rec['confidence'] == 'MEDIUM':
                score += 2
            else:
                score += 1
            if rec['strength'] == 'HIGH':
                score += 2
            elif rec['strength'] == 'MEDIUM':
                score += 1
            return -score
        recommendations.sort(key=sort_key)
        return recommendations