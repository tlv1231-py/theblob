# Dashboard — Launch & Usage

## Quick Start

```powershell
# From project root
$env:PYTHONPATH = "."
streamlit run dashboard/app.py
```

The dashboard opens at `http://localhost:8501` in your browser.

## Prerequisites

Install dashboard dependencies if not already done:

```powershell
pip install streamlit plotly
# or install all requirements:
pip install -r requirements.txt
```

## Pages

| Page | Purpose |
|---|---|
| **Portfolio** | Equity curve, current positions & weights, daily/cumulative PnL, drawdown |
| **Signals** | Today's top signals with scores, full history, score distribution |
| **Backtest Lab** | Parameter controls, run backtests against DB history, compare experiments |
| **Risk Monitor** | Exposure vs limits, drawdown state, breach alerts |

## Notes

- The dashboard is **read-only** — it does not modify the pipeline, database schema, or any core modules.
- Data refreshes on every page load (60-second cache TTL for most queries).
- Backtest Lab is the one exception: running a backtest **writes** a new row to the `experiments` table (this is by design — all experiments must be logged).
- Run `python run_pipeline.py` after market close each day to ingest new data and update PnL.
- Rolling Sharpe shows "n/a" until ≥5 trading days of PnL history exist.
