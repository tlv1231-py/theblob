"""
Create strategy_params table and seed all parameters for all 8 strategies.
Run once: python scripts/seed_strategy_params.py
"""
from datetime import datetime
from sqlalchemy import text
from data.database import engine, Base, get_session
from data.models import StrategyParam

# Create table if it doesn't exist
Base.metadata.create_all(engine, tables=[StrategyParam.__table__])

PARAMS = [
    # ── MOMENTUM ────────────────────────────────────────────────────────────────
    ("momentum", "rebalance_days",  "5",    "days",    "Rebalance every N days"),
    ("momentum", "universe_size",   "94",   "stocks",  "Number of symbols screened"),
    ("momentum", "lookback_months", "12",   "months",  "Return lookback window"),
    ("momentum", "skip_months",     "1",    "months",  "Recent months excluded from return"),
    ("momentum", "top_n",           "5",    "stocks",  "Number of positions held"),
    ("momentum", "max_position",    "20",   "%",       "Max single position size"),
    ("momentum", "daily_dd_halt",   "2",    "%",       "Daily drawdown trading halt"),
    ("momentum", "total_dd_halt",   "10",   "%",       "Total drawdown trading halt"),
    ("momentum", "slippage_bps",    "5",    "bps",     "Assumed slippage per fill"),

    # ── MEAN REVERSION ───────────────────────────────────────────────────────────
    ("mean_reversion", "universe_size",    "94",   "stocks",  "Number of symbols screened"),
    ("mean_reversion", "zscore_threshold", None,   "σ",       "Z-score entry threshold"),
    ("mean_reversion", "lookback_days",    None,   "days",    "Rolling mean lookback"),
    ("mean_reversion", "max_position",     None,   "%",       "Max single position size"),
    ("mean_reversion", "stop_loss",        None,   "%",       "Stop-loss per position"),
    ("mean_reversion", "slippage_bps",     None,   "bps",     "Assumed slippage per fill"),

    # ── TREND FOLLOWING ──────────────────────────────────────────────────────────
    ("trend_following", "ma_period",       None,   "days",    "Moving average period"),
    ("trend_following", "rebalance_freq",  None,   "days",    "Rebalance frequency"),
    ("trend_following", "universe_size",   None,   "ETFs",    "Number of ETFs in universe"),
    ("trend_following", "max_position",    None,   "%",       "Max single position size"),
    ("trend_following", "total_dd_halt",   None,   "%",       "Total drawdown trading halt"),
    ("trend_following", "slippage_bps",    None,   "bps",     "Assumed slippage per fill"),

    # ── CARRY ────────────────────────────────────────────────────────────────────
    ("carry", "rebalance_freq",   None,   "days",    "Rebalance frequency"),
    ("carry", "universe_size",    None,   "assets",  "Number of assets screened"),
    ("carry", "top_n",            None,   "assets",  "Number of positions held"),
    ("carry", "max_position",     None,   "%",       "Max single position size"),
    ("carry", "total_dd_halt",    None,   "%",       "Total drawdown trading halt"),
    ("carry", "slippage_bps",     None,   "bps",     "Assumed slippage per fill"),

    # ── QUALITY / LOW VOL ────────────────────────────────────────────────────────
    ("quality_low_vol", "universe_size",  "94",   "stocks",  "Number of symbols screened"),
    ("quality_low_vol", "max_beta",       None,   "β",       "Maximum allowed beta"),
    ("quality_low_vol", "top_n",          None,   "stocks",  "Number of positions held"),
    ("quality_low_vol", "rebalance_freq", None,   "days",    "Rebalance frequency"),
    ("quality_low_vol", "max_position",   None,   "%",       "Max single position size"),
    ("quality_low_vol", "total_dd_halt",  None,   "%",       "Total drawdown trading halt"),
    ("quality_low_vol", "slippage_bps",   None,   "bps",     "Assumed slippage per fill"),

    # ── INTRADAY ─────────────────────────────────────────────────────────────────
    ("daytrader", "market_open",     "9:30am",  "ET",    "Session start time"),
    ("daytrader", "market_close",    "3:45pm",  "ET",    "Hard close — all positions flat"),
    ("daytrader", "rvol_threshold",  "1.5",     "×",     "Minimum relative volume to enter"),
    ("daytrader", "rr_ratio",        "2",       ":1",    "Reward-to-risk ratio on bracket"),
    ("daytrader", "stop_pct",        "0.5",     "%",     "Stop-loss distance from entry"),
    ("daytrader", "target_pct",      "1.0",     "%",     "Profit target distance from entry"),
    ("daytrader", "slippage_bps",    None,      "bps",   "Assumed slippage per fill"),

    # ── VOLATILITY SELLING ───────────────────────────────────────────────────────
    ("volatility_selling", "iv_rank_min",    None,   "IVR",    "Minimum IV rank to sell"),
    ("volatility_selling", "delta_target",   None,   "Δ",      "Target delta for short option"),
    ("volatility_selling", "dte_entry",      None,   "days",   "Days to expiration at entry"),
    ("volatility_selling", "dte_close",      None,   "days",   "Days to expiration — close early"),
    ("volatility_selling", "profit_target",  None,   "%",      "Close at % of max profit"),
    ("volatility_selling", "max_position",   None,   "%",      "Max notional per position"),

    # ── EARNINGS DRIFT ───────────────────────────────────────────────────────────
    ("earnings_drift", "entry_delay",      "1",    "days",   "Days after announcement to enter"),
    ("earnings_drift", "hold_min",         "5",    "days",   "Minimum hold period"),
    ("earnings_drift", "hold_max",         "20",   "days",   "Maximum hold period"),
    ("earnings_drift", "surprise_min",     None,   "%",      "Minimum EPS beat to qualify"),
    ("earnings_drift", "max_position",     None,   "%",      "Max single position size"),
    ("earnings_drift", "total_dd_halt",    None,   "%",      "Total drawdown trading halt"),
    ("earnings_drift", "slippage_bps",     None,   "bps",    "Assumed slippage per fill"),
]

with get_session() as s:
    inserted = 0
    skipped  = 0
    for (strategy, param, value, unit, label) in PARAMS:
        existing = s.execute(
            text("SELECT id FROM strategy_params WHERE strategy=:s AND param=:p"),
            {"s": strategy, "p": param}
        ).fetchone()
        if existing:
            skipped += 1
            continue
        s.add(StrategyParam(
            strategy=strategy, param=param,
            value=value, unit=unit, label=label,
            updated_at=datetime.utcnow(),
        ))
        inserted += 1
    s.commit()

print(f"Done — {inserted} inserted, {skipped} already existed.")
