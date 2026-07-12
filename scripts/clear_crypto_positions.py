"""One-shot: clear all rows from crypto_positions (stale state cleanup)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import delete
from data.database import get_session
from data.models import CryptoPosition

with get_session() as s:
    result = s.execute(delete(CryptoPosition))
    s.commit()
    print(f"Deleted {result.rowcount} stale crypto position(s).")
