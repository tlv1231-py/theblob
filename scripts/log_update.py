"""Post a deployment/update event to the pipeline terminal feed.

Run after any meaningful code change or dashboard update so it shows
up in the terminal's system feed.

Usage:
    python scripts/log_update.py "deployed hover tooltips + queued actions panel"
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from data.pipeline_log import log_event

msg = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else "update deployed"
log_event(date.today(), "UPDATE", msg)
print(f"[terminal] posted: {msg}")
