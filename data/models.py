"""SQLAlchemy ORM models — the DB tables."""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, Integer,
    JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_bar"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    expected_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    as_of_date: Mapped[str] = mapped_column(String(10), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    params_version: Mapped[str] = mapped_column(String(50), default="")


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    signal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FillRecord(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fill_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    filled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    net_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    positions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PnLRecord(Base):
    __tablename__ = "pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CapitalEvent(Base):
    """Tracks deposits and withdrawals — lets the equity curve show 'invested capital' as a baseline."""
    __tablename__ = "capital_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)          # positive = deposit, negative = withdrawal
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChartAnnotation(Base):
    __tablename__ = "chart_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    annotation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="orange")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PipelineEvent(Base):
    """One structured log entry per pipeline step. Powers the terminal feed."""
    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # INGEST | SIGNAL | ENTRY | EXIT | HOLD | RISK_VETO | SNAPSHOT | PNL | INTRADAY | START | COMPLETE | MARKET_OPEN | MARKET_CLOSE | UPDATE | FETCH
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CryptoPosition(Base):
    """Open crypto_momentum positions — persists between GitHub Actions runs."""
    __tablename__ = "crypto_positions"

    id:           Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:       Mapped[str]   = mapped_column(String(20), nullable=False, unique=True)
    direction:    Mapped[str]   = mapped_column(String(10), nullable=False)  # long | short
    qty:          Mapped[float] = mapped_column(Float, nullable=False)
    entry_price:  Mapped[float] = mapped_column(Float, nullable=False)
    stop_price:   Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    entered_at:   Mapped[datetime] = mapped_column(DateTime, nullable=False)
    order_id:     Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategy:     Mapped[str]  = mapped_column(String(50), default="crypto_momentum")


class StreamEvent(Base):
    """One event bound for the Stream page — real or simulated.

    Stream HQ and the Stream page never share a browser: the stream renders in
    a headless Chromium on the streaming host, while HQ runs wherever the
    operator is. postMessage/localStorage cannot cross that gap, so this table
    IS the channel. Everything the Blob reacts to that did not come from the
    trading engine passes through here, which is what makes both the
    hold-and-release countdown and simulation possible.

    Lifecycle: queued -> released -> consumed. A queued row is visible in HQ but
    invisible to the stream; only `released` (or release_at <= now) is eligible
    to be picked up. `cancelled` never fires. The Stream page stamps consumed_at
    so HQ can prove an event actually landed rather than assuming it did.
    """
    __tablename__ = "stream_events"

    id:         Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # donation | superchat | supersticker | follow | subscription | membership_gift
    # | bits | raid | chat | trade_enter | trade_exit | risk_breach
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source:     Mapped[str] = mapped_column(String(20), nullable=False, default="simulated")
    # streamlabs | simulated | engine
    payload:    Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status:     Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    # queued | released | consumed | cancelled
    release_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StreamHealth(Base):
    """Heartbeat from one component of the streaming stack.

    Each component writes its own row; HQ only reads. This is deliberate — a
    health check that cannot observe the thing it reports on is worse than no
    check at all, because it shows green while the stream is dead.

    `stream_page` is written BY the rendered page itself, which is the only way
    to catch the specific failure that kills this setup: Streamlit drops the
    idle websocket, the page freezes, and the encoder happily pushes a dead
    screenshot to YouTube for hours. Nothing outside the render can see that.

    `encoder` must be written by an agent on the streaming host — ffmpeg speed,
    fps, CPU. Until that agent exists those checks report "no agent", never OK.
    """
    __tablename__ = "stream_health"

    id:        Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # stream_page | encoder | host | engine
    status:    Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    # ok | degraded | down
    detail:      Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class NavSnapshot(Base):
    """Intraday NAV samples written every ~30s by the dashboard crypto poller."""
    __tablename__ = "nav_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)


class StrategyParam(Base):
    """One tunable parameter per row. Single source of truth for all strategy config."""
    __tablename__ = "strategy_params"
    __table_args__ = (UniqueConstraint("strategy", "param", name="uq_strategy_param"),)

    id:          Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy:    Mapped[str]         = mapped_column(String(50), nullable=False, index=True)
    param:       Mapped[str]         = mapped_column(String(60), nullable=False)
    value:       Mapped[str | None]  = mapped_column(String(100), nullable=True)   # null = unset
    unit:        Mapped[str]         = mapped_column(String(30), nullable=False, default="")
    label:       Mapped[str]         = mapped_column(String(100), nullable=False)
    updated_at:  Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    cagr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    logged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
