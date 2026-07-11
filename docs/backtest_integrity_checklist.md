# Backtest Integrity Checklist

Before any backtest result is considered valid, confirm all of the following:

## Data Integrity

- [ ] **No look-ahead bias** — signals use only data available at decision time (close prices from prior day, not same-day)
- [ ] **Point-in-time data** — no survivorship bias in universe selection (use only symbols that existed at the time)
- [ ] **Splits and dividends adjusted correctly** — use `adj_close` throughout; verify with corporate action data

## Execution Realism

- [ ] **Realistic fill assumptions** — no mid-price fills; use next-open or VWAP as fill proxy
- [ ] **Slippage modeled** — minimum 5bps per side for liquid equities
- [ ] **Transaction costs included** — commissions, spread, market impact

## Out-of-Sample Discipline

- [ ] **Out-of-sample period held out** — minimum 20% of data never touched during development
- [ ] **No parameter fitting on full sample** — walk-forward or expanding-window validation

## Logging

- [ ] **Results logged to experiment tracker** — with date, params, hypothesis, and quantitative summary
- [ ] **Backtest period explicitly stated** — start date, end date, universe
- [ ] **Benchmark comparison included** — vs. SPY buy-and-hold at minimum

## Risk Metrics Reported

- [ ] CAGR
- [ ] Sharpe ratio
- [ ] Sortino ratio
- [ ] Maximum drawdown
- [ ] Annualized volatility
- [ ] Turnover
- [ ] Average slippage cost
