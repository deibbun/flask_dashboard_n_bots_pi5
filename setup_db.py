# setup_db.py

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

db_params = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS'),
    'host': os.getenv('DB_HOST'),
    'port': '5432'
}

def bootstrap_database():
    print("Booting PostgreSQL Architecture with Strategy Isolation...")
    try:
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()

        # 1. Master Account Balance Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS account_balance (
                account_id SERIAL PRIMARY KEY,
                liquid_usd NUMERIC NOT NULL,
                last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            INSERT INTO account_balance (liquid_usd) 
            VALUES (10009.58);
        """)

        # 2. Live Positions Tracker (Primary Key is now symbol + strategy_id)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol VARCHAR(20),
                strategy_id VARCHAR(50),
                status VARCHAR(20) DEFAULT 'WAITING',
                qty NUMERIC DEFAULT 0.0,
                entry_price NUMERIC DEFAULT 0.0,
                initial_margin_usd NUMERIC DEFAULT 0.0,
                sl_price NUMERIC DEFAULT 0.0,
                tp_price NUMERIC DEFAULT 0.0,
                last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, strategy_id)
            );
        """)

        cur.execute("""
            INSERT INTO positions (strategy_id, symbol, status, qty, entry_price, initial_margin_usd, sl_price, tp_price)
            VALUES
                ('master', 'BTC/USD', 'WAITING', 0, 0, 0, 0, 0),
                ('master', 'ETH/USD', 'WAITING', 0, 0, 0, 0, 0),
                ('master', 'SOL/USD', 'WAITING', 0, 0, 0, 0, 0),
                ('btc_pure', 'BTC/USD', 'WAITING', 0, 0, 0, 0, 0),
                ('eth_pure', 'ETH/USD', 'WAITING', 0, 0, 0, 0, 0),
                ('sol_pure', 'SOL/USD', 'WAITING', 0, 0, 0, 0, 0)
            ON CONFLICT (symbol, strategy_id)
            DO NOTHING;
        """)
        # 3. Live Market Data table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS live_market_data (
                symbol VARCHAR(20) PRIMARY KEY,
                price NUMERIC(16,4) DEFAULT 0.0000,
                sma NUMERIC(16,4) DEFAULT 0.0000,
                atr_pct NUMERIC DEFAULT 0.0,
                vol_multiplier NUMERIC DEFAULT 1.0,
                is_hunting BOOLEAN DEFAULT false,
                momentum_ignition BOOLEAN DEFAULT false,
                last_updated TIMESTAMPZ DEFAULT CURRENT_TIMESTAMP,
                atr NUMERIC(18,8)
            );
        """)

        cur.execute("""
            INSERT INTO live_market_data(symbol, price, sma, atr_pct, vol_multiplier, is_hunting, momentum_ignition, last_updated, atr)
            VALUES
                ('BTC/USD', 0, 0, 0, 1.0, false, false, CURRENT_TIMESTAMP, 0),
                ('ETH/USD', 0, 0, 0, 1.0, false, false, CURRENT_TIMESTAMP, 0),
                ('SOL/USD', 0, 0, 0, 1.0, false, false, CURRENT_TIMESTAMP, 0)
            ON CONFLICT (symbol)
            DO NOTHING;
        """)

        # 3. Paper Trade Ledger (Added strategy_id)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20),
                strategy_id VARCHAR(50),
                side VARCHAR(10),
                price NUMERIC,
                amount NUMERIC,
                total_usd NUMERIC,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Hourly Equity Snapshots (Added strategy_id)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id SERIAL PRIMARY KEY,
                snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                strategy_id VARCHAR(50),
                available_cash_usd NUMERIC,
                reserved_cash_usd NUMERIC,
                open_positions_value_usd NUMERIC,
                total_net_worth_usd NUMERIC
            );
        """)
        
        # 5. Bot Journals table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_journals (
                id SERIAL PRIMARY KEY,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                strategy_id VARCHAR(20) NOT NULL,
                log_level VARCHAR(20) NOT NULL,
                message TEXT NOT NULL
            );
        """)
        
        # 6. Treasury State
        cur.execute("""
            CREATE TABLE IF NOT EXISTS treasury_state (
                id SERIAL PRIMARY KEY,
                updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                play_name VARCHAR(50),
                total_capital NUMERIC(12, 2),
                reserve NUMERIC(12, 2),
                allocations JSONB
            );
        """)

        conn.commit()
        print("✅ Database Architecture Built Successfully!")

    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    bootstrap_database()
