from pathlib import Path
from typing import Any

import yaml
from loguru import logger


_REGISTRY_PATH = Path(__file__).parent / "strategy_registry.yaml"
_VALID_STATUSES = {"research", "backtest", "paper", "live"}


def load_registry() -> list[dict[str, Any]]:
    with _REGISTRY_PATH.open() as f:
        data = yaml.safe_load(f)
    strategies = data.get("strategies", [])
    for s in strategies:
        if s.get("status") not in _VALID_STATUSES:
            raise ValueError(
                f"Strategy '{s['name']}' has invalid status '{s.get('status')}'. "
                f"Must be one of: {_VALID_STATUSES}"
            )
    logger.debug(f"Loaded {len(strategies)} strategies from registry.")
    return strategies


def get_strategy(name: str) -> dict[str, Any]:
    strategies = load_registry()
    for s in strategies:
        if s["name"] == name:
            return s
    raise KeyError(f"Strategy '{name}' not found in registry.")


def list_strategies(status: str | None = None) -> list[dict[str, Any]]:
    strategies = load_registry()
    if status:
        strategies = [s for s in strategies if s.get("status") == status]
    return strategies
