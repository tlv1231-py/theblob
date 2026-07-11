"""Abstract broker interface. Swap paper <-> live without touching core logic."""
from abc import ABC, abstractmethod

from data.schemas import Fill, Order


class BrokerAdapter(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Fill:
        """Submit an order and return a Fill."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> int:
        """Return current share count. Positive = long, negative = short."""
        ...
