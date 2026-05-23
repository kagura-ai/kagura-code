from __future__ import annotations

import pytest

from kagura_code.models import ModelSpec, UnknownModelError, resolve_model


def make_models() -> list[ModelSpec]:
    return [
        ModelSpec(
            alias="claude-qwen3-coder-1m",
            display_name="Qwen3 Coder 480B [1M]",
            ollama_model="qwen3-coder:480b-cloud",
            context_window=1_000_000,
            max_output_tokens=65_536,
        ),
        ModelSpec(
            alias="claude-gemma4-31b",
            display_name="Gemma 4 31B",
            ollama_model="gemma4:31b-cloud",
            context_window=128_000,
            max_output_tokens=8_192,
        ),
    ]


def test_resolve_known_alias_returns_spec():
    models = make_models()
    spec = resolve_model("claude-qwen3-coder-1m", models)
    assert spec.ollama_model == "qwen3-coder:480b-cloud"
    assert spec.context_window == 1_000_000


def test_resolve_unknown_alias_raises():
    models = make_models()
    with pytest.raises(UnknownModelError) as exc_info:
        resolve_model("not-a-real-model", models)
    msg = str(exc_info.value)
    assert "not-a-real-model" in msg
    assert "claude-qwen3-coder-1m" in msg
    assert "claude-gemma4-31b" in msg


def test_modelspec_alias_must_start_with_claude_prefix():
    with pytest.raises(ValueError, match="must start with 'claude-'"):
        ModelSpec(
            alias="qwen-1m",
            display_name="x",
            ollama_model="y",
            context_window=1,
            max_output_tokens=1,
        )


def test_modelspec_context_window_must_be_positive():
    with pytest.raises(ValueError, match="context_window"):
        ModelSpec(
            alias="claude-x",
            display_name="x",
            ollama_model="y",
            context_window=0,
            max_output_tokens=1,
        )
