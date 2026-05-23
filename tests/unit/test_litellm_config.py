from __future__ import annotations

import yaml

from kagura_code.litellm_config import render_litellm_config
from kagura_code.models import ModelSpec


def specs() -> list[ModelSpec]:
    return [
        ModelSpec("claude-a-1m", "A", "a:cloud", 1_000_000, 65_536),
        ModelSpec("claude-b", "B", "b:cloud", 128_000, 8_192),
    ]


def test_render_produces_valid_yaml():
    out = render_litellm_config(
        specs(),
        ollama_api_base="http://localhost:11434/v1",
        master_key="kagura-code-dummy",
    )
    parsed = yaml.safe_load(out)
    assert "model_list" in parsed
    assert "general_settings" in parsed


def test_render_includes_all_model_aliases():
    out = render_litellm_config(
        specs(),
        ollama_api_base="http://localhost:11434/v1",
        master_key="kagura-code-dummy",
    )
    parsed = yaml.safe_load(out)
    names = {m["model_name"] for m in parsed["model_list"]}
    assert names == {"claude-a-1m", "claude-b"}


def test_render_prefixes_model_with_ollama_chat_provider():
    """We use ollama_chat/ (not openai/) so LiteLLM forwards Ollama-native
    params like num_ctx to the daemon. See litellm_config.tpl for rationale.
    """
    out = render_litellm_config(
        specs(), ollama_api_base="http://localhost:11434", master_key="x",
    )
    parsed = yaml.safe_load(out)
    models = {m["model_name"]: m["litellm_params"]["model"] for m in parsed["model_list"]}
    assert models["claude-a-1m"] == "ollama_chat/a:cloud"
    assert models["claude-b"] == "ollama_chat/b:cloud"


def test_render_includes_num_ctx_per_model():
    """num_ctx is set per-model to the context_window — the Ollama daemon
    uses this as the active KV-cache size. context_window itself matches the
    daemon's reported size for the model.
    """
    out = render_litellm_config(
        specs(), ollama_api_base="http://localhost:11434", master_key="x",
    )
    parsed = yaml.safe_load(out)
    by_alias = {m["model_name"]: m["litellm_params"] for m in parsed["model_list"]}
    assert by_alias["claude-a-1m"]["num_ctx"] == 1_000_000
    assert by_alias["claude-b"]["num_ctx"] == 128_000


def test_render_sets_master_key():
    out = render_litellm_config(
        specs(), ollama_api_base="http://localhost:11434/v1", master_key="my-secret",
    )
    parsed = yaml.safe_load(out)
    assert parsed["general_settings"]["master_key"] == "my-secret"


def test_render_sets_api_base_from_argument():
    out = render_litellm_config(
        specs(), ollama_api_base="http://example.test/v1", master_key="x",
    )
    parsed = yaml.safe_load(out)
    for m in parsed["model_list"]:
        assert m["litellm_params"]["api_base"] == "http://example.test/v1"


def test_render_does_not_include_router_alias():
    models = [
        ModelSpec(alias="claude-x", display_name="X", ollama_model="x:cloud",
                  context_window=400000, max_output_tokens=32000),
    ]
    yaml_out = render_litellm_config(
        models,
        ollama_api_base="http://localhost:11434",
        master_key="dummy",
    )
    assert "claude-router" not in yaml_out


def test_render_num_ctx_matches_ollama_spec_for_deepseek():
    """DeepSeek's context_window matches the daemon's reported 1M, so num_ctx == 1M."""
    models = [
        ModelSpec(
            alias="claude-deepseek-v4-pro",
            display_name="DeepSeek V4 Pro",
            ollama_model="deepseek-v4-pro:cloud",
            context_window=1_048_576,
            max_output_tokens=32_768,
        ),
    ]
    out = render_litellm_config(
        models, ollama_api_base="http://localhost:11434", master_key="x",
    )
    parsed = yaml.safe_load(out)
    by_alias = {m["model_name"]: m["litellm_params"] for m in parsed["model_list"]}
    assert by_alias["claude-deepseek-v4-pro"]["num_ctx"] == 1_048_576


def test_render_omits_wildcard_when_no_fallback_alias():
    out = render_litellm_config(
        specs(), ollama_api_base="http://localhost:11434", master_key="x",
    )
    parsed = yaml.safe_load(out)
    names = [m["model_name"] for m in parsed["model_list"]]
    assert "*" not in names


def test_render_appends_wildcard_when_fallback_alias_given():
    out = render_litellm_config(
        specs(),
        ollama_api_base="http://localhost:11434",
        master_key="x",
        wildcard_fallback_alias="claude-a-1m",
    )
    parsed = yaml.safe_load(out)
    by_name = {m["model_name"]: m["litellm_params"] for m in parsed["model_list"]}
    assert "*" in by_name
    assert by_name["*"]["model"] == "ollama_chat/a:cloud"
    assert by_name["*"]["num_ctx"] == 1_000_000


def test_render_wildcard_appears_last_for_specificity_ordering():
    """LiteLLM's PatternMatchRouter sorts by specificity, but we keep the
    wildcard entry physically last so the YAML stays human-readable.
    """
    out = render_litellm_config(
        specs(),
        ollama_api_base="http://localhost:11434",
        master_key="x",
        wildcard_fallback_alias="claude-a-1m",
    )
    parsed = yaml.safe_load(out)
    names = [m["model_name"] for m in parsed["model_list"]]
    assert names[-1] == "*"


def test_render_raises_when_fallback_alias_not_in_model_list():
    import pytest
    with pytest.raises(ValueError, match="not in models list"):
        render_litellm_config(
            specs(),
            ollama_api_base="http://localhost:11434",
            master_key="x",
            wildcard_fallback_alias="claude-does-not-exist",
        )


def test_render_num_ctx_matches_ollama_spec_for_256k_model():
    """256K-class models match the daemon's reported 262144 directly."""
    models = [
        ModelSpec(
            alias="claude-qwen3-coder",
            display_name="Qwen3 Coder",
            ollama_model="qwen3-coder:480b-cloud",
            context_window=262_144,
            max_output_tokens=65_536,
        ),
    ]
    out = render_litellm_config(
        models, ollama_api_base="http://localhost:11434", master_key="x",
    )
    parsed = yaml.safe_load(out)
    by_alias = {m["model_name"]: m["litellm_params"] for m in parsed["model_list"]}
    assert by_alias["claude-qwen3-coder"]["num_ctx"] == 262_144
