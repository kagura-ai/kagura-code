from __future__ import annotations

import json

from kagura_code.lean import cleanup_lean_home, make_lean_home


def test_make_lean_home_creates_dir_with_settings(tmp_path):
    home = make_lean_home(tmp_path)
    assert home.exists()
    settings = home / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert isinstance(data, dict)
    # Sanity: no plugins/skills/MCP in the minimal settings
    assert "plugins" not in data
    assert "skills" not in data
    assert "mcpServers" not in data


def test_make_lean_home_is_idempotent(tmp_path):
    h1 = make_lean_home(tmp_path)
    h2 = make_lean_home(tmp_path)
    assert h1 == h2
    assert h1.exists()


def test_cleanup_lean_home_removes_dir(tmp_path):
    home = make_lean_home(tmp_path)
    cleanup_lean_home(home)
    assert not home.exists()


def test_cleanup_lean_home_idempotent_when_missing(tmp_path):
    home = tmp_path / "nonexistent"
    cleanup_lean_home(home)  # should not raise


def test_make_lean_home_creates_local_bin_dir(tmp_path):
    home = make_lean_home(tmp_path)
    assert (home / ".local" / "bin").is_dir()


def test_make_lean_home_settings_is_empty(tmp_path):
    """The .claude/settings.json in lean-home should be blank so that
    plugins, MCP servers, skills, and hooks are not loaded for the session.
    """
    home = make_lean_home(tmp_path)
    import json as _json
    data = _json.loads((home / ".claude" / "settings.json").read_text())
    assert data == {}


def test_make_lean_home_copies_real_claude_json_for_onboarding_state(tmp_path):
    """~/.claude.json (login + onboarding state) must be inherited so that
    Claude Code does not re-run the first-run wizard.
    """
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    (real_home / ".claude.json").write_text(
        '{"hasCompletedOnboarding": true, "theme": "dark"}'
    )

    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    copied = home / ".claude.json"
    assert copied.exists()
    import json as _json
    data = _json.loads(copied.read_text())
    assert data["hasCompletedOnboarding"] is True


def test_make_lean_home_no_claude_json_when_real_missing(tmp_path):
    """Missing ~/.claude.json in real-home is non-fatal (best effort)."""
    real_home = tmp_path / "real-home-empty"
    real_home.mkdir()  # no .claude.json inside
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    assert not (home / ".claude.json").exists()


def test_make_lean_home_symlinks_real_claude_if_present(tmp_path):
    # Create a fake real-home with a claude binary
    real_home = tmp_path / "real-home"
    (real_home / ".local" / "bin").mkdir(parents=True)
    real_claude = real_home / ".local" / "bin" / "claude"
    real_claude.write_text("#!/bin/sh\necho fake")
    real_claude.chmod(0o755)

    lean_base = tmp_path / "lean-base"
    home = make_lean_home(lean_base, real_home=real_home)
    link = home / ".local" / "bin" / "claude"
    assert link.exists()


def test_make_lean_home_inlines_claude_md_imports(tmp_path):
    """User's CLAUDE.md @<path> imports must be inline-expanded so the
    spawned claude session doesn't prompt about external imports.
    """
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    (real_home / ".claude" / "CLAUDE.md").write_text(
        "My preferences:\n@helper.md\nEnd.\n"
    )
    (real_home / ".claude" / "helper.md").write_text(
        "EXPANDED CONTENT"
    )

    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    claude_md = home / ".claude" / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "@helper.md" not in content
    assert "EXPANDED CONTENT" in content
    assert "My preferences:" in content


def test_make_lean_home_inlines_absolute_path_imports(tmp_path):
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    external = tmp_path / "external.md"
    external.write_text("ABSOLUTE")
    (real_home / ".claude" / "CLAUDE.md").write_text(f"@{external}\n")
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    content = (home / ".claude" / "CLAUDE.md").read_text()
    assert "ABSOLUTE" in content
    assert "@" not in content  # no unresolved import


def test_make_lean_home_inlines_tilde_path_imports(tmp_path):
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    (real_home / "notes.md").write_text("TILDE EXPANDED")
    (real_home / ".claude" / "CLAUDE.md").write_text("@~/notes.md\n")
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    content = (home / ".claude" / "CLAUDE.md").read_text()
    assert "TILDE EXPANDED" in content


def test_make_lean_home_leaves_missing_imports_as_is(tmp_path):
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    (real_home / ".claude" / "CLAUDE.md").write_text("@nonexistent.md\n")
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    content = (home / ".claude" / "CLAUDE.md").read_text()
    # Missing import is left as the literal @path line so the user notices
    assert "@nonexistent.md" in content


def test_make_lean_home_recurses_imports(tmp_path):
    """@A.md → @B.md → terminal content. Both should be inlined."""
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    (real_home / ".claude" / "CLAUDE.md").write_text("@A.md\n")
    (real_home / ".claude" / "A.md").write_text("LEVEL_A\n@B.md\n")
    (real_home / ".claude" / "B.md").write_text("LEVEL_B")
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    content = (home / ".claude" / "CLAUDE.md").read_text()
    assert "LEVEL_A" in content
    assert "LEVEL_B" in content


def test_make_lean_home_bounded_recursion_does_not_hang(tmp_path):
    """a → @b, b → @a (cycle). Must terminate, leaving @a unresolved at
    the recursion limit rather than looping forever.
    """
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    (real_home / ".claude" / "CLAUDE.md").write_text("@a.md\n")
    (real_home / ".claude" / "a.md").write_text("@b.md")
    (real_home / ".claude" / "b.md").write_text("@a.md")
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    # If this returned, it didn't hang. Content can be anything (depends on
    # exactly where the depth limit fires); we just assert it terminated
    # with a string.
    content = (home / ".claude" / "CLAUDE.md").read_text()
    assert isinstance(content, str)


def test_make_lean_home_no_claude_md_when_real_missing(tmp_path):
    real_home = tmp_path / "real-home-empty"
    (real_home / ".claude").mkdir(parents=True)
    home = make_lean_home(tmp_path / "lean-base", real_home=real_home)
    # Lean session simply has no user instructions, which is fine
    assert not (home / ".claude" / "CLAUDE.md").exists()
