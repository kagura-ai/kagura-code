from __future__ import annotations

from unittest.mock import patch

from kagura_code.config import Config, OllamaCloudConfig, RtkConfig
from kagura_code.doctor import (
    check_claude_installed,
    check_cloud_model_pulled,
    check_litellm_version,
    check_ollama_cli_installed,
    check_ollama_daemon_reachable,
    check_python_version,
    check_router_alias_configured,
    check_rtk_integration,
)
from kagura_code.models import ModelSpec


def make_cfg(rtk_enabled: str = "auto") -> Config:
    return Config(
        default_model="claude-x-1m",
        models=[ModelSpec("claude-x-1m", "X", "x:cloud", 1_000_000, 8_192)],
        ollama_cloud=OllamaCloudConfig(api_base="http://localhost:11434/v1"),
        rtk=RtkConfig(enabled=rtk_enabled),
    )


def test_check_python_version_passes_on_supported(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "version_info", (3, 12, 1, "final", 0))
    ok, msg = check_python_version()
    assert ok is True
    assert "3.12" in msg


def test_check_python_version_fails_on_unsupported(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "version_info", (3, 10, 8, "final", 0))
    ok, _msg = check_python_version()
    assert ok is False


def test_check_litellm_version_passes_on_safe():
    with patch("kagura_code.doctor._litellm_version", return_value="1.83.4"):
        ok, msg = check_litellm_version()
    assert ok is True
    assert "1.83.4" in msg


def test_check_litellm_version_fails_on_compromised():
    for bad in ("1.82.7", "1.82.8"):
        with patch("kagura_code.doctor._litellm_version", return_value=bad):
            ok, msg = check_litellm_version()
        assert ok is False
        assert "compromised" in msg.lower()


def test_check_claude_installed_passes_when_present(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho 'claude 2.1.144'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    ok, msg = check_claude_installed()
    assert ok is True
    assert str(fake) in msg


def test_check_claude_installed_fails_when_missing(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    ok, _msg = check_claude_installed()
    assert ok is False


def test_check_ollama_cli_installed_passes_when_present(tmp_path, monkeypatch):
    fake = tmp_path / "ollama"
    fake.write_text("#!/bin/sh\necho 'ollama version 0.20.2'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    ok, msg = check_ollama_cli_installed()
    assert ok is True
    assert str(fake) in msg


def test_check_ollama_cli_installed_fails_when_missing(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    ok, _msg = check_ollama_cli_installed()
    assert ok is False


def test_check_ollama_daemon_reachable_passes_on_200(httpserver):
    httpserver.expect_request("/api/version").respond_with_json({"version": "0.20.2"})
    # The check is hard-wired to localhost:11434, so patch the URL builder.
    with patch("kagura_code.doctor._OLLAMA_API_BASE", f"http://127.0.0.1:{httpserver.port}"):
        ok, msg = check_ollama_daemon_reachable()
    assert ok is True
    assert "0.20.2" in msg


def test_check_ollama_daemon_reachable_fails_when_unreachable(monkeypatch):
    # Patch to an unreachable port
    with patch("kagura_code.doctor._OLLAMA_API_BASE", "http://127.0.0.1:1"):
        ok, msg = check_ollama_daemon_reachable()
    assert ok is False
    assert "unreachable" in msg.lower() or "connection" in msg.lower() or "refused" in msg.lower()


def test_check_cloud_model_pulled_passes_when_any_cloud_model_present(httpserver):
    httpserver.expect_request("/api/tags").respond_with_json({
        "models": [
            {"name": "qwen3-coder:480b-cloud", "size": 0},
            {"name": "gemma4:31b", "size": 19_000_000_000},
        ],
    })
    with patch("kagura_code.doctor._OLLAMA_API_BASE", f"http://127.0.0.1:{httpserver.port}"):
        ok, msg = check_cloud_model_pulled()
    assert ok is True
    assert "qwen3-coder:480b-cloud" in msg


def test_check_cloud_model_pulled_fails_when_no_cloud_models(httpserver):
    httpserver.expect_request("/api/tags").respond_with_json({
        "models": [{"name": "qwen3:0.6b", "size": 522_000_000}],
    })
    with patch("kagura_code.doctor._OLLAMA_API_BASE", f"http://127.0.0.1:{httpserver.port}"):
        ok, msg = check_cloud_model_pulled()
    assert ok is False
    assert "signin" in msg.lower() or "no cloud" in msg.lower()


def test_check_rtk_passes_when_installed_and_auto():
    cfg = make_cfg(rtk_enabled="auto")
    with patch("shutil.which", return_value="/home/user/.local/bin/rtk"):
        ok, msg = check_rtk_integration(cfg)
    assert ok is True
    assert "/home/user/.local/bin/rtk" in msg
    assert "hook" in msg.lower() or "settings" in msg.lower()


def test_check_rtk_optional_when_auto_and_missing():
    cfg = make_cfg(rtk_enabled="auto")
    with patch("shutil.which", return_value=None):
        ok, msg = check_rtk_integration(cfg)
    assert ok is True
    assert "optional" in msg.lower()


def test_check_rtk_fails_when_required_and_missing():
    cfg = make_cfg(rtk_enabled="true")
    with patch("shutil.which", return_value=None):
        ok, msg = check_rtk_integration(cfg)
    assert ok is False
    assert "not on path" in msg.lower() or "required" in msg.lower()


def test_check_router_alias_configured_ok():
    cfg = Config(
        default_model="claude-gemma4-31b",
        models=[
            ModelSpec("claude-gemma4-31b", "Gemma4 31B", "gemma4:31b-cloud", 262_144, 8_192),
            ModelSpec("claude-x-1m", "X", "x:cloud", 1_000_000, 8_192),
        ],
        ollama_cloud=OllamaCloudConfig(api_base="http://localhost:11434/v1"),
        rtk=RtkConfig(enabled="auto"),
    )
    ok, msg = check_router_alias_configured(cfg, "claude-gemma4-31b")
    assert ok is True
    assert "claude-gemma4-31b" in msg


def test_check_router_alias_configured_missing():
    cfg = make_cfg()
    ok, msg = check_router_alias_configured(cfg, "claude-gemma4-31b")
    assert ok is False
    assert "--list-models" in msg
