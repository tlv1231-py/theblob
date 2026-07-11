"""Aggregates and routes signals from all active strategy generators."""
from datetime import date

from loguru import logger

from data.schemas import Signal
from registry.registry import list_strategies
from signals.momentum_signals import MomentumSignalGenerator

_GENERATORS = {
    "momentum": MomentumSignalGenerator,
}


def generate_all_signals(as_of_date: date) -> list[Signal]:
    """Run all paper/live strategies and return combined signal list."""
    active = list_strategies(status="paper") + list_strategies(status="live")
    all_signals: list[Signal] = []

    for strategy_meta in active:
        name = strategy_meta["name"]
        gen_cls = _GENERATORS.get(name)
        if gen_cls is None:
            logger.warning(f"No generator registered for strategy '{name}'. Skipping.")
            continue
        try:
            gen = gen_cls()
            signals = gen.generate(as_of_date)
            all_signals.extend(signals)
        except Exception as exc:
            logger.error(f"Signal generation failed for '{name}': {exc}")

    return all_signals
