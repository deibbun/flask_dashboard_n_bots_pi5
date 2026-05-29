# app.py

import os
from dotenv import load_dotenv

load_dotenv()

from kraken_auth import KrakenPrivateClient
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, render_template

from apscheduler.schedulers.background import BackgroundScheduler
from logger import BotLogger
from market_oracle import KrakenOracle
from treasury_manager import TreasuryManager
from execution_engine import ExecutionEngine

class ExecutiveEngineApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.json.compact = False
        self.app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
        self.db_log = BotLogger()
        
        # --- The CFO Module (LIVE MODE Engaged) ---
        self.LIVE_MODE = False
        
        if self.LIVE_MODE:
            print("🔐 Authenticating with Kraken Private API...")
            self.db_log.environment = "LIVE"
            kraken_client = KrakenPrivateClient()
            wallet = kraken_client.get_live_usd_balance()
            
            if wallet is not None:
                live_usd = wallet["USD"]
                self.treasury = TreasuryManager(self.db_log, initial_capital=live_usd, environment=self.db_log.environment)
                self.treasury.verify_reality(live_usd)
                self.db_log.success("TREASURY", f"LIVE MODE ENGAGED.  Synced Real Capital: ${live_usd}")
            else:
                print("❌ FAILED TO FETCH LIVE BALANCE.  Defaulting to lockdown.")
                self.treasury = TreasuryManager(self.db_log, initial_capital=0.0, environment=self.db_log.environment)
                self.treasury.reconciliation_light = "RED"
        else:
            self.db_log.environment = "PAPER"
            self.treasury = TreasuryManager(self.db_log, initial_capital=10009.58, environment=self.db_log.environment)
        
        self._setup_routes()
        self._setup_scheduler()

    def _setup_scheduler(self):
        print("⚙️ Initializing Executive Engine Background Workers...")
        self.scheduler = BackgroundScheduler()
        self.oracle = KrakenOracle(self.db_log)

        # Trigger the master heartbeat instead of just the oracle
        self.scheduler.add_job(func=self._engine_tick, trigger="interval", minutes=5)
        self.scheduler.add_job(func=self._engine_tick, trigger="date") 
        self.scheduler.start()

    def get_db_connection(self):
        return psycopg2.connect(
            dbname=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT', '5432')
        )

    def _engine_tick(self):
        """The master loop: Oracle scans the market, Execution Engine makes the trades."""
        # 1. The Eyes: Update prices and indicator math
        self.oracle.scan_markets()
        
        # 2. The Hands: Execute based on the CURRENT active dimension
        trader = ExecutionEngine(self.db_log, environment=self.db_log.environment)
        trader.run_cycle()

    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template('index.html')

        @self.app.route('/api/test_connection')
        def test_connection():
            try:
                conn = self.get_db_connection()
                conn.close()
                return jsonify({"status": "success", "message": f"Successfully connected!"})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)})
                
        @self.app.route('/api/toggle_mode', methods=['POST'])
        def toggle_mode():
            self.LIVE_MODE = not self.LIVE_MODE
            
            if self.LIVE_MODE:
                print("🔐 Switching to LIVE MODE...")
                self.db_log.environment = "LIVE"
                kraken_client = KrakenPrivateClient()
                wallet = kraken_client.get_live_usd_balance()
                
                if live_balance is not None:
                    live_usd = wallet["USD"]
                    self.treasury = TreasuryManager(self.db_log, initial_capital=live_usd, environment=self.db_log.environment)
                    self.treasury.verify_reality(live_usd)
                    self.db_log.success("TREASURY", f"LIVE MODE ENGAGED.  Synced Real Capital:  ${live_usd}")
                else:
                    self.db_log.error("TREASURY", "FAILED TO FETCH LIVE BALANCE.  Defaulting to lockdown.")
                    self.treasury = TreasuryManager(self.db_log, initial_capital=0.0, environment=self.db_log.environment)
                    self.treasury.reconciliation_light = "RED"
            else:
                print("📝 Switching to PAPER TRADING...")
                self.db_log.environment = "PAPER"
                self.treasury = TreasuryManager(self.db_log, initial_capital=10009.58, environment=self.db_log.environment)
                self.db_log.info("TREASURY", "PAPER TRADING ENGAGED.  Synced Paper Capital:  ${initial_capital}")
                
            return jsonify({"status": "success", "live_mode": self.LIVE_MODE})
            
        @self.app.route('/api/override/close', methods=['POST'])
        def override_close():
            from flask import request
            data = request.json
            strat = data.get('strategy_id')
            sym = data.get('symbol')
            env_str = "LIVE" if self.LIVE_MODE else "PAPER"
            
            try:
                conn = self.get_db_connection()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                
                # 1. Grab the current live price and the original entry price
                cur.execute("""
                    SELECT p.qty, p.entry_price, m.price as current_price
                    FROM positions p
                    JOIN live_market_data m ON p.symbol = m.symbol
                    WHERE p.strategy_id = %s AND p.symbol = %s AND p.environment = %s AND p.status = 'OPEN';
                """, (strat, sym, env_str))
                
                pos = cur.fetchone()
                if pos:
                    entry_price = float(pos['entry_price'])
                    current_price = float(pos['current_price'])
                    qty = float(pos['qty'])
                    
                    # 2. Calculate the exact math of the early exit
                    pnl = (current_price - entry_price) * qty
                    
                    # 3. Liquidate the position
                    cur.execute("""
                        UPDATE positions 
                        SET status = 'WAITING', qty = 0, entry_price = 0, sl_price = 0, tp_price = 0, initial_margin_usd = 0, last_updated = CURRENT_TIMESTAMP
                        WHERE strategy_id = %s AND symbol = %s AND environment = %s;
                    """, (strat, sym, env_str))
                    conn.commit()
                    
                    # 4. Log the override to the dashboard
                    log_level = "SUCCESS" if pnl > 0 else "WARNING"
                    self.db_log._write_log("EXECUTIVE", log_level, f"MANUAL OVERRIDE [{sym}] - Close: ${current_price:.2f} | PnL: ${pnl:.2f}")
                    
                cur.close()
                conn.close()
                return jsonify({"status": "success", "message": "Position liquidated."})
            except Exception as e:
                import traceback
                traceback.print_exc()
                return jsonify({"status": "error", "message": str(e)})

        @self.app.route('/api/data')
        def get_data():
            data = {"balance": 0, "positions": [], "market": [], "journals": []}
            env_str = "LIVE" if self.LIVE_MODE else "PAPER"
            try:
                conn = self.get_db_connection()
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("SELECT total_capital FROM treasury_state WHERE environment = %s ORDER BY updated_time DESC LIMIT 1;", (env_str,))
                balance_row = cur.fetchone()
                if balance_row: data["balance"] = float(balance_row['total_capital'])
                data["live_mode"] = self.LIVE_MODE

                cur.execute("SELECT strategy_id, symbol, status, qty, entry_price, sl_price, tp_price FROM positions WHERE environment = %s ORDER BY status ASC, strategy_id ASC;", (env_str,))
                data["positions"] = cur.fetchall()

                cur.execute("SELECT symbol, price, closed_price, sma, atr_pct, is_hunting, momentum_ignition, rsi FROM live_market_data;")
                data["market"] = cur.fetchall()

                # FIXED: Correct ORDER BY, aliased columns to match your JS, fixed the loop indentation
                cur.execute("SELECT updated_time, strategy_id, log_level, message FROM bot_journals WHERE environment = %s ORDER BY updated_time DESC LIMIT 15;", (env_str,))
                journals = []
                for row in cur.fetchall():
                    # Overwrite the datetime object with a string so your JS gets exactly what it expects
                    row['updated_time'] = row['updated_time'].strftime("%m-%d-%y %H:%M:%S")
                    journals.append(row)
                data["journals"] = journals
                
                # --- Inject CFO Treasury State to UI ---
                data["treasury"] = {
                    "total_capital": self.treasury.total_capital,
                    "reserve": self.treasury.reserve,
                    "allocations": self.treasury.allocations,
                    "reconciliation_light": self.treasury.reconciliation_light
                }

                cur.close()
                conn.close()
                return jsonify({"status": "success", "data": data})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)})

    def run(self):
        self.app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    server = ExecutiveEngineApp()
    server.run()