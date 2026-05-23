from __future__ import annotations

from typer.testing import CliRunner

from kagura_code.cli import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "kagura-code" in result.stdout.lower()


def test_list_models_shows_default_aliases():
    result = runner.invoke(app, ["--list-models"])
    assert result.exit_code == 0
    assert "claude-deepseek-v4-pro" in result.stdout
    assert "claude-deepseek-v4-pro" in result.stdout
    assert "claude-kimi-k2" in result.stdout
    assert "claude-gemma4-31b" in result.stdout


def test_unknown_model_exits_nonzero():
    result = runner.invoke(app, ["--model", "claude-nonexistent"])
    assert result.exit_code != 0
    assert "unknown model" in (result.stdout + (result.stderr or "")).lower()


def test_help_lists_options():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--model" in result.stdout
    assert "--doctor" in result.stdout
    assert "--list-models" in result.stdout
    assert "--proxy-only" in result.stdout


def test_help_lists_lean_flag():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--lean" in result.stdout


def test_cli_help_includes_router_model_flag():
    result = runner.invoke(app, ["--help"])
    assert "--router-model" in result.stdout


def test_cli_doctor_exits_zero(monkeypatch):
    monkeypatch.setattr("kagura_code.cli.run_diagnostics", lambda cfg, **_kw: True)
    result = runner.invoke(app, ["--doctor"])
    assert result.exit_code == 0


def test_positional_model_arg_selects_alias(monkeypatch):
    """`kagura-code <alias>` selects that alias via the positional argument."""
    captured: dict[str, str] = {}

    def fake_resolve(alias, _models):
        captured["alias"] = alias
        raise SystemExit(99)  # short-circuit before proxy/middleware spin-up

    monkeypatch.setattr("kagura_code.cli.resolve_model", fake_resolve)
    runner.invoke(app, ["claude-kimi-k2"])
    assert captured["alias"] == "claude-kimi-k2"


def test_explicit_model_flag_wins_over_positional(monkeypatch):
    """When both `--model` and a positional alias are supplied, `--model` wins."""
    captured: dict[str, str] = {}

    def fake_resolve(alias, _models):
        captured["alias"] = alias
        raise SystemExit(99)

    monkeypatch.setattr("kagura_code.cli.resolve_model", fake_resolve)
    runner.invoke(app, ["claude-kimi-k2", "--model", "claude-qwen3-coder"])
    assert captured["alias"] == "claude-qwen3-coder"


def test_complete_model_returns_matching_aliases():
    """`_complete_model(prefix)` lists configured aliases starting with the prefix."""
    from kagura_code.cli import _complete_model

    matches = _complete_model("claude-d")
    assert "claude-deepseek-v4-pro" in matches
    assert all(m.startswith("claude-d") for m in matches)

    # Empty prefix returns the full set of configured aliases.
    all_aliases = _complete_model("")
    assert "claude-deepseek-v4-pro" in all_aliases
    assert "claude-kimi-k2" in all_aliases


def test_show_completion_exits_zero():
    """Typer's --show-completion should print a script and exit cleanly."""
    result = runner.invoke(app, ["--show-completion", "bash"])
    assert result.exit_code == 0
    # Sanity: the printed script mentions the program name somewhere.
    assert "kagura" in result.stdout.lower() or "complete" in result.stdout.lower()


def test_option_shaped_extras_not_parsed_as_model(monkeypatch):
    """Regression: `kagura-code --some-claude-flag` (no `--`) must not bind
    `--some-claude-flag` to the positional model_arg. The unknown option
    should fall through to ctx.args for forwarding to the spawned claude."""
    captured: dict[str, str] = {}

    def fake_resolve(alias, _models):
        captured["alias"] = alias
        raise SystemExit(99)

    monkeypatch.setattr("kagura_code.cli.resolve_model", fake_resolve)
    result = runner.invoke(app, ["--print", "hello"])
    # Must not error out as "unknown model '--print'":
    combined = (result.stdout or "") + (result.stderr or "")
    assert "unknown model" not in combined.lower()
    # resolve_model should have been called with the default alias, not --print:
    assert captured["alias"] != "--print"
