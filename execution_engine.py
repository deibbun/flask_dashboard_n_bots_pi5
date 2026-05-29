import os
from dotenv import load_dotenv

load_dotenv()

import json
import psycopg2
from psycopg2.extras import RealDictCursor

class ExecutionEngine:
    def __init__(self, logger, environment="PAPER"):
        self.logger = logger
        self.environment = environment
        self.db_params = {
            'dbname': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASS'),
            'host': os.getenv('DB_HOST'),
            'port': os.getenv('DB_PORT', '5432')
        }

    def _get_db_connection(self):
        return psycopg2.connect(**self.db_params)

    def _get_current_allocations(self):
        """Asks the Treasury how much money each strategy is allowed to use."""
        sql = "SELECT allocations FROM treasury_state WHERE environment = %s ORDER BY updated_time DESC LIMIT 1;"
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, (self.environment,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row['allocations']:
                # ARMOR: Force it into a dictionary if Postgres hands us a string
                if isinstance(row['allocations'], str):
                    return json.loads(row['allocations'])
                return row['allocations']
            return {}
        except Exception as e:
            self.logger.error("EXECUTION", f"Failed to read treasury allocations: {e}")
            return {}

    def process_entries(self):
        """Scans for WAITING positions where the Oracle is hunting."""
        allocations = self._get_current_allocations()
        
        # ARMOR: Cast is_hunting to text to bypass Boolean vs Varchar crashes
        sql = """
            SELECT p.strategy_id, p.symbol, m.price, m.atr_pct, m.is_hunting
            FROM positions p
            JOIN live_market_data m ON p.symbol = m.symbol
            WHERE p.status = 'WAITING' 
            AND p.environment = %s 
            AND m.is_hunting::text IN ('true', 'True', '1', 't');
        """
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, (self.environment,))
            opportunities = cur.fetchall()

            for opp in opportunities:
                strat = opp['strategy_id']
                sym = opp['symbol']
                price = float(opp['price'])
                atr_pct = float(opp['atr_pct']) / 100.0
                
                allocated_funds = float(allocations.get(strat, 0.0))
                if allocated_funds < 1.0:
                    continue
                
                qty = allocated_funds / price
                sl_price = price - (price * atr_pct)
                tp_price = price + (price * (atr_pct * 1.5))
                
                update_sql = """
                    UPDATE positions 
                    SET status = 'OPEN', qty = %s, entry_price = %s, sl_price = %s, tp_price = %s, initial_margin_usd = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE strategy_id = %s AND symbol = %s AND environment = %s;
                """
                cur.execute(update_sql, (qty, price, sl_price, tp_price, allocated_funds, strat, sym, self.environment))
                conn.commit()
                
                self.logger.success(strat, f"ENTRY TRIGGERED [{sym}] - Qty: {qty:.4f} | Entry: ${price:.2f} | SL: ${sl_price:.2f} | TP: ${tp_price:.2f}")

            cur.close()
            conn.close()
        except Exception as e:
            self.logger.error("EXECUTION", f"Entry processing failed: {e}")

    def process_exits(self):
        """Scans OPEN positions to see if Stop Loss or Take Profit was hit."""
        sql = """
            SELECT p.strategy_id, p.symbol, p.qty, p.entry_price, p.sl_price, p.tp_price, m.price as current_price
            FROM positions p
            JOIN live_market_data m ON p.symbol = m.symbol
            WHERE p.status = 'OPEN' AND p.environment = %s;
        """
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, (self.environment,))
            open_positions = cur.fetchall()

            for pos in open_positions:
                strat = pos['strategy_id']
                sym = pos['symbol']
                current_price = float(pos['current_price'])
                sl_price = float(pos['sl_price'])
                tp_price = float(pos['tp_price'])
                
                exit_triggered = False
                exit_reason = ""
                
                if current_price <= sl_price:
                    exit_triggered = True
                    exit_reason = "STOP LOSS"
                elif current_price >= tp_price:
                    exit_triggered = True
                    exit_reason = "TAKE PROFIT"
                    
                if exit_triggered:
                    entry_price = float(pos['entry_price'])
                    qty = float(pos['qty'])
                    pnl = (current_price - entry_price) * qty
                    
                    update_sql = """
                        UPDATE positions 
                        SET status = 'WAITING', qty = 0, entry_price = 0, sl_price = 0, tp_price = 0, initial_margin_usd = 0, last_updated = CURRENT_TIMESTAMP
                        WHERE strategy_id = %s AND symbol = %s AND environment = %s;
                    """
                    cur.execute(update_sql, (strat, sym, self.environment))
                    t_state = cur.fetchone()
                    if t_state:
                        new_capital = round(float(t_state['total_capital']) + pnl, 2)
                        new_reserve = round(float(t_state['reserve']) + pnl, 2)
                        
                        # Handle JSON string formatting
                        allocs = t_state['allocations'] if isinstance(t_state['allocations'], str) else json.dumps(t_state['allocations'])
                        
                        cur.execute("""
                            INSERT INTO treasury_state (environment, play_name, total_capital, reserve, allocations)
                            VALUES (%s, %s, %s, %s, %s);
                        """, (self.environment, t_state['play_name'], new_capital, new_reserve, allocs))
                    
                    conn.commit()
                    
                    log_level = "SUCCESS" if pnl > 0 else "WARNING"
                    self.logger.success(strat, f"EXIT TRIGGERED [{sym}] - Reason: {exit_reason} | Close: ${current_price:.2f} | PnL: ${pnl:.2f}")

            cur.close()
            conn.close()
        except Exception as e:
            self.logger.error("EXECUTION", f"Exit processing failed: {e}")

    def run_cycle(self):
        self.process_exits()
        self.process_entries()