"""Centralized risk parameters. All risk enforcement lives in /risk."""

# Per-trade risk as fraction of portfolio
MAX_RISK_PER_TRADE = 0.01        # 1%
MAX_RISK_PER_TRADE_HARD = 0.02   # 2% hard cap

# Sector / theme exposure caps
MAX_SECTOR_EXPOSURE = 0.10       # 10% of portfolio per sector

# Portfolio-level exposure
MAX_GROSS_EXPOSURE = 1.0         # 100% — no leverage initially
MAX_NET_EXPOSURE = 0.80          # 80% net long cap

# Drawdown controls
MAX_DAILY_DRAWDOWN = 0.02        # 2% daily loss limit — pause trading
MAX_TOTAL_DRAWDOWN = 0.10        # 10% total drawdown — halt system

# Stop-loss defaults (strategy can override via strategy_params/)
DEFAULT_STOP_LOSS_PCT = 0.05     # 5% below entry

# Position sizing
# Top-5 equal-weight = 20% per position. 1% risk / 5% stop = $20K = 20% of $100K.
MAX_POSITION_SIZE = 0.20         # 20% of portfolio in a single position (top-5 config)
MIN_POSITION_SIZE = 0.01         # 1% minimum (avoid noise trades)
