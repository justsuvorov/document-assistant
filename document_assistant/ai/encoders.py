from abc import ABC, abstractmethod


class Encoder(ABC):
    @abstractmethod
    def prepared_data(self, source: str) -> str:
        pass


class TextEncoder(Encoder):
    """Prepare and clean origin data for LLM. Make it efficient for query"""
    def prepared_data(self, source: str) -> str:
        pass
