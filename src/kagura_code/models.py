"""Model specifications and alias resolution."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """A single model alias backed by an Ollama Cloud model.

    The `alias` must start with `claude-` so that Claude Code's gateway
    discovery filter accepts it.

    `recommended_use` is a short, human-readable string displayed in
    `kagura-code --list-models` to help users pick the right model for
    a session. Empty string means no recommendation shown.
    """
    alias: str
    display_name: str
    ollama_model: str
    context_window: int
    max_output_tokens: int
    recommended_use: str = ""

    def __post_init__(self) -> None:
        if not self.alias.startswith("claude-"):
            raise ValueError(
                f"alias must start with 'claude-'; got {self.alias!r}"
            )
        if self.context_window <= 0:
            raise ValueError(f"context_window must be positive; got {self.context_window}")
        if self.max_output_tokens <= 0:
            raise ValueError(f"max_output_tokens must be positive; got {self.max_output_tokens}")


class UnknownModelError(ValueError):
    """Raised when a requested alias is not in the configured model list."""


def resolve_model(alias: str, models: list[ModelSpec]) -> ModelSpec:
    for m in models:
        if m.alias == alias:
            return m
    available = ", ".join(sorted(m.alias for m in models))
    raise UnknownModelError(
        f"unknown model {alias!r}. Available: {available}. "
        f"Run 'kagura-code --list-models' to see all options."
    )
