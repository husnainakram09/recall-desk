"""Model adapter interface. Swapping Token Factory for vLLM is a config change."""

from typing import Protocol


class ModelAdapter(Protocol):
    def extract(self, text: str) -> dict: ...
