"""Shared signal interface. All signal generators must implement this."""
from abc import ABC, abstractmethod
from datetime import date

from data.schemas import Signal


class BaseSignalGenerator(ABC):
    strategy: str

    @abstractmethod
    def generate(self, as_of_date: date) -> list[Signal]:
        """Generate signals as of a given market date.

        IMPORTANT: Must not use any data with date > as_of_date.
        """
        ...
