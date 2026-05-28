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

class ExecutiveEngineApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.json.compact = False
        self.app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
        self.db_log = BotLogger()
        
        # --- The CFO Module (LIVE MODE Engaged) ---
        self.LIVE_MODE = True
        
        if self.LIVE_MODE:
            print("🔐 Authenticating with Kraken Private API...")
            kraken_client = KrakenPrivateClient()
            live_balance = kraken_client.get_live_usd_balance()
            
            if live_balance is not None:
                self.treasury = TreasuryManager(self.db_log, initial_capital=live_balance)
                self.treasury.verify_reality(live_balance)
                self.db_log.success("TREASURY", f"LIVE MODE ENGAGED.  Synced Real Capital: ${live_balance}")
            else:
                print("❌ FAILED TO FETCH LIVE BALANCE.  Defaulting to lockdown.")
                self.treasury = TreasuryManager(self.db_log, initial_capital=0.0)
                self.treasury.reconciliation_light = "RED"
        else:
            self.treasury = TreasuryManager(self.db_log, initial_capital=10009.58)
        
        self._setup_routes()
        self._setup_scheduler()

    def _setup_scheduler(self):
        print("⚙️ Initializing Executive Engine Background Workers...")
        self.scheduler = BackgroundScheduler()
        self.oracle = KrakenOracle(self.db_log)

        self.scheduler.add_job(func=self.oracle.scan_markets, trigger="interval", minutes=5)
        self.scheduler.add_job(func=self.oracle.scan_markets, trigger="date")
        self.scheduler.start()

    def get_db_connection(self):
        return psycopg2.connect(
            dbname=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT', '5432')
        )

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

        @self.app.route('/api/data')
        def get_data():
            data = {"balance": 0, "positions": [], "market": [], "journals": []}
            try:
                conn = self.get_db_connection()
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("SELECT liquid_usd FROM account_balance ORDER BY last_updated DESC LIMIT 1;")
                balance_row = cur.fetchone()
                if balance_row: data["balance"] = float(balance_row['liquid_usd'])

                cur.execute("SELECT strategy_id, symbol, status, qty, entry_price, sl_price, tp_price FROM positions ORDER BY status ASC, strategy_id ASC;")
                data["positions"] = cur.fetchall()

                cur.execute("SELECT symbol, price, closed_price, sma, atr_pct, is_hunting, momentum_ignition, rsi FROM live_market_data;")
                data["market"] = cur.fetchall()

                # FIXED: Correct ORDER BY, aliased columns to match your JS, fixed the loop indentation
                cur.execute("SELECT updated_time, strategy_id, log_level, message FROM bot_journals ORDER BY updated_time DESC LIMIT 15;")
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