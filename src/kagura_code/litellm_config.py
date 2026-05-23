"""Render a LiteLLM proxy YAML config for a given set of ModelSpecs."""
from __future__ import annotations

import dataclasses
from importlib.resources import files
from typing import Any

import jinja2

from .models import ModelSpec


def render_litellm_config(
    models: list[ModelSpec],
    *,
    ollama_api_base: str,
    master_key: str,
    wildcard_fallback_alias: str | None = None,
) -> str:
    """Return the YAML text of a LiteLLM proxy config.

    The rendered config targets an OpenAI-compatible endpoint (the local
    Ollama daemon by default) and uses a dummy api_key per model entry
    since the daemon handles cloud auth via `ollama signin`.

    If `wildcard_fallback_alias` is set to a known alias, a catch-all
    `model_name: "*"` entry is appended pointing at that model.  LiteLLM's
    PatternMatchRouter scores exact matches as more specific than wildcards,
    so explicit aliases keep their own deployment; unmatched aliases (e.g.
    Anthropic-native names like `claude-opus-4-5` selected via Claude Code's
    `/model` picker) silently route to the fallback instead of failing.
    """
    template_src = files("kagura_code._vendor").joinpath("litellm_config.tpl").read_text()
    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # YAML, not HTML  # noqa: S701
    )
    template = env.from_string(template_src)
    augmented: list[dict[str, Any]] = [
        {**dataclasses.asdict(m), "num_ctx": m.context_window}
        for m in models
    ]
    fallback: dict[str, Any] | None = None
    if wildcard_fallback_alias is not None:
        for entry in augmented:
            if entry["alias"] == wildcard_fallback_alias:
                fallback = entry
                break
        if fallback is None:
            raise ValueError(
                f"wildcard_fallback_alias {wildcard_fallback_alias!r} not in models list"
            )
    return template.render(
        models=augmented,
        ollama_api_base=ollama_api_base,
        master_key=master_key,
        fallback=fallback,
    )
