"""crypto_momentum entry point.

Runs forever on Fly.io — connects to Alpaca crypto WebSocket,
processes 1-min bars, executes paper fills, logs everything to
Supabase so the dashboard Status bar fires on every trade.

Usage:
  python run_crypto.py

Environment (set as Fly.io secrets):
  ALPACA_API_KEY
  ALPACA_SECRET_KEY
  DATABASE_URL
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def main() -> None:
    from strategies.crypto.strategy import CryptoMomentumStrategy
    from strategies.crypto.feed import CryptoFeed

    strategy = CryptoMomentumStrategy()

    feed = CryptoFeed(
        symbols = strategy.cfg["universe"],
        on_bar  = strategy.on_bar,
    )

    logger.info("[crypto] Feed starting — streaming 1-min bars 24/7")
    await feed.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[crypto] Stopped.")
