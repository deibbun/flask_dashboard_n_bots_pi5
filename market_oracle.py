# market_oracle.py

import os
from dotenv import load_dotenv

load_dotenv()

import time
import requests
import psycopg2

class KrakenOracle:
    def __init__(self, logger):
        self.logger = logger
        self.base_url = "https://api.kraken.com/0/public"
        
        # Kraken is notoriously weird about ticker symbols
        # Have to translate the dashboard symbols into Kraken's language
        self.symbol_map = {
            'BTC/USD': 'XXBTZUSD',
            'ETH/USD': 'XETHZUSD',
            'SOL/USD': 'SOLUSD'
        }
        
        self.db_params = {
            'dbname': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASS'),
            'host': os.getenv('DB_HOST'),
            'port': os.getenv('DB_PORT', '5432')
        }
        
    def _get_db_connection(self):
        return psycopg2.connect(**self.db_params)
            
    def fetch_ohlc_data(self, standard_symbol, interval=60):
        """Pulls the latest hourly candlestick data from Kraken."""
        kraken_symbol = self.symbol_map.get(standard_symbol)
        url = f"{self.base_url}/OHLC?pair={kraken_symbol}&interval={interval}"
            
        try:
            response = requests.get(url)
            data = response.json()
                
            if data['error']:
                self.logger.error("ORACLE", f"Kraken API Error for {standard_symbol}: {data['error']}")
                return None
                
            # Kraken returns data nested under the pair name
            # Format:  [time, open, high, low, close, vwap, volume, count]
            candles = data['result'][kraken_symbol]
            return candles
                
        except Exception as e:
            self.logger.error("ORACLE", f"Network failure fetching {standard_symbol}: {e}")
            return None
                
    def calculate_indicators(self, candles, period=14):
        """Calculates indicators strictly on closed candles, but returns live price for the UI."""
        if not candles or len(candles) < period + 2:
            return None, None, None, None, None, None
            
        # 1. THE UI DATA: The absolute last candle in the list is currently breathing
        live_price = float(candles[-1][4])
        
        # 2. THE BRAIN DATA: We isolate the closed history (drop the live candle)
        closed_history = candles[-(period+2):-1]
        
        closes = [float(candle[4]) for candle in closed_history]
        highs = [float(candle[2]) for candle in closed_history]
        lows = [float(candle[3]) for candle in closed_history]
        volumes = [float(candle[6]) for candle in closed_history]
        
        # The last fully locked price
        closed_price = closes[-1]
        
        # SMA of the last 14 closed candles
        sma = sum(closes[1:]) / period
        
        # 1. ATR Percentage
        true_ranges = [highs[i] - lows[i] for i in range(1, len(closes))]
        atr = sum(true_ranges) / period
        atr_pct = (atr / closed_price) * 100 if closed_price > 0 else 0
        
        # 2. Momentum Ignition
        avg_volume = sum(volumes[1:-1]) / (period - 1)
        current_volume = volumes[-1]
        price_moving_up = closes[-1] > closes[-2]
        momentum_ignition = (current_volume > (avg_volume * 2)) and price_moving_up
        
        # 3. RSI
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
                
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        return live_price, closed_price, sma, round(atr_pct, 2), momentum_ignition, round(rsi, 2)
            
    def update_database(self, symbol, live_price, closed_price, sma, atr_pct, momentum, rsi):
        """Pushes the data into the database using strictly locked candle logic."""
        
        # THE MASTER ENTRY LOGIC
        # We compare the LOCKED closed_price against the SMA, completely ignoring the live flicker
        is_hunting = (closed_price > sma) and momentum and (rsi < 70)
        
        sql = """
            UPDATE live_market_data
            SET price = %s, closed_price = %s, sma = %s, atr_pct = %s, momentum_ignition = %s, rsi = %s, is_hunting = %s, last_updated = CURRENT_TIMESTAMP
            WHERE symbol = %s;
        """
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            # We save the live_price so your UI updates, but is_hunting is bulletproof
            cur.execute(sql, (live_price, closed_price, sma, atr_pct, momentum, rsi, is_hunting, symbol))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            self.logger.error("ORACLE", f"Database update failed for {symbol}: {e}")
                
    def scan_markets(self):
        """The main loop function that checks all tracked pairs."""
        self.logger.info("ORACLE", "Initiating market scan...")
        
        for symbol in self.symbol_map.keys():
            candles = self.fetch_ohlc_data(symbol, interval=60)
            
            if candles:
                # Unpack all SIX variables now
                live_price, closed_price, sma, atr_pct, momentum, rsi = self.calculate_indicators(candles, period=14)
                
                if live_price and sma:
                    self.update_database(symbol, live_price, closed_price, sma, atr_pct, momentum, rsi)
                    
            time.sleep(1.5)
            
        self.logger.success("ORACLE", "Market scan complete. Dashboard updated.")
            
# If this file is run directly, it will do one single scan to test the pipes.
if __name__ == "__main__":
    from logger import BotLogger
    test_logger = BotLogger()
    oracle = KrakenOracle(test_logger)
    oracle.scan_markets()
                