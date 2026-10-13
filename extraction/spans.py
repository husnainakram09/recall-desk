"""Split notice text into numbered spans the model cites as evidence."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    id: str  # "S1", "S2", ... in document order
    text: str  # the source line, unmodified


def split_spans(text: str) -> tuple[Span, ...]:
    lines = [line for line in text.splitlines() if line.strip()]
    return tuple(Span(f"S{i}", line) for i, line in enumerate(lines, 1))
