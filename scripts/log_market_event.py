"""Log a market open or close event to the pipeline terminal feed.

Called by GitHub Actions at 9:30am and 4:00pm ET on trading days.

Usage:
    python scripts/log_market_event.py open
    python scripts/log_market_event.py close
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from ingestion.calendar import is_trading_day
from data.pipeline_log import log_event

event = sys.argv[1].lower() if len(sys.argv) > 1 else "open"
today = date.today()

if not is_trading_day(today):
    print(f"[market] {today} is not a trading day — skipping")
    sys.exit(0)

if event == "open":
    log_event(today, "MARKET_OPEN", "NYSE open  ·  9:30am ET")
    print("[market] logged: MARKET_OPEN")
else:
    log_event(today, "MARKET_CLOSE", "NYSE closed  ·  4:00pm ET  ·  pipeline incoming")
    print("[market] logged: MARKET_CLOSE")
