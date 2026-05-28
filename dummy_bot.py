# dummy_bot.py

from logger import BotLogger
import time

# Initialize the Logger
db_log = BotLogger()
strategy = "MACD.Sniper_V1"

print("Starting bot...")

# Simulate bot behavior and logging
db_log.info(strategy, "Bot initialized.  Searching for market anomalies.")
time.sleep(1)

db_log.warning(strategy, "Exchange API latency is currently above 200ms.")
time.sleep(1)

db_log.error(strategy, "Failed to place Stop Loss.  Retrying API connection.")
time.sleep(1)

db_log.success(strategy, "Filled LONG order on BTC/USD at $64,200.")

print("Mock logs injected successfully.")