"""Discord webhook alerts for signals, fills, and system events."""
import httpx
from loguru import logger

from config.settings import settings
from data.schemas import Fill, Signal


def _post(payload: dict) -> None:
    url = settings.discord_webhook_url
    if not url:
        logger.debug("[discord] No webhook URL configured — skipping alert.")
        return
    try:
        resp = httpx.post(url, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"[discord] Alert failed: {exc}")


def alert_signal(signal: Signal) -> None:
    emoji = "🟢" if signal.direction.value == "long" else "🔴"
    _post({
        "content": (
            f"{emoji} **Signal** | `{signal.strategy}` | `{signal.symbol}` "
            f"{signal.direction.value.upper()} | score={signal.score:.2f} | "
            f"er={signal.expected_return:.1%} | {signal.as_of_date}"
        )
    })


def alert_fill(fill: Fill) -> None:
    _post({
        "content": (
            f"📋 **Fill** | `{fill.symbol}` {fill.side.value.upper()} "
            f"{fill.quantity} @ ${fill.fill_price:.4f} | "
            f"slippage=${fill.slippage:.2f}"
        )
    })


def alert_risk_veto(message: str) -> None:
    _post({"content": f"🛑 **Risk Veto** | {message}"})


def alert_system(message: str) -> None:
    _post({"content": f"ℹ️ **System** | {message}"})
