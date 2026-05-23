from __future__ import annotations

from pathlib import Path

import pytest

from kagura_code.config import ConfigError, load_config


def write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_load_default_config_when_no_user_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KAGURA_CODE_CONFIG", raising=False)
    cfg = load_config(explicit_path=None)
    assert cfg.default_model == "claude-deepseek-v4-pro"
    assert any(m.alias == "claude-deepseek-v4-pro" for m in cfg.models)
    assert any(m.alias == "claude-gemma4-31b" for m in cfg.models)
    assert cfg.ollama_cloud.api_base == "http://localhost:11434"


def test_explicit_path_overrides_search(tmp_path):
    user = write(tmp_path / "u.toml", """
[default]
model = "claude-x-1m"

[ollama_cloud]
api_base = "http://example.test/v1"

[[models]]
alias = "claude-x-1m"
display_name = "X"
ollama_model = "x:cloud"
context_window = 1000000
max_output_tokens = 1000
""")
    cfg = load_config(explicit_path=user)
    assert cfg.default_model == "claude-x-1m"
    assert [m.alias for m in cfg.models] == ["claude-x-1m"]
    assert cfg.ollama_cloud.api_base == "http://example.test/v1"


def test_user_models_extend_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path / ".config" / "kagura-code" / "config.toml", """
[[models]]
alias = "claude-extra-1m"
display_name = "Extra"
ollama_model = "extra:cloud"
context_window = 1000000
max_output_tokens = 1000
""")
    cfg = load_config(explicit_path=None)
    aliases = [m.alias for m in cfg.models]
    assert "claude-deepseek-v4-pro" in aliases  # default preserved
    assert "claude-extra-1m" in aliases  # user-added


def test_user_models_override_by_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path / ".config" / "kagura-code" / "config.toml", """
[[models]]
alias = "claude-deepseek-v4-pro"
display_name = "Qwen3 [Custom]"
ollama_model = "qwen3-coder:480b-cloud"
context_window = 500000
max_output_tokens = 8192
""")
    cfg = load_config(explicit_path=None)
    spec = next(m for m in cfg.models if m.alias == "claude-deepseek-v4-pro")
    assert spec.context_window == 500_000  # overridden
    assert spec.display_name == "Qwen3 [Custom]"


def test_user_can_override_api_base(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path / ".config" / "kagura-code" / "config.toml", """
[ollama_cloud]
api_base = "http://remote-daemon.test:11434/v1"
""")
    cfg = load_config(explicit_path=None)
    assert cfg.ollama_cloud.api_base == "http://remote-daemon.test:11434/v1"


def test_invalid_toml_raises_config_error(tmp_path):
    p = write(tmp_path / "bad.toml", "not = valid = toml")
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(explicit_path=p)


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(explicit_path=tmp_path / "nonexistent.toml")


def test_default_config_has_rtk_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KAGURA_CODE_CONFIG", raising=False)
    cfg = load_config(explicit_path=None)
    assert cfg.rtk.enabled == "auto"


def test_default_config_includes_summarizer_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KAGURA_CODE_CONFIG", raising=False)
    cfg = load_config(explicit_path=None)
    aliases = {m.alias for m in cfg.models}
    assert "claude-qwen35-summ" in aliases
    summ = next(m for m in cfg.models if m.alias == "claude-qwen35-summ")
    assert summ.ollama_model == "qwen3.5:397b-cloud"
    assert summ.context_window == 262_144
