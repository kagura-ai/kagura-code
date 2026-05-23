"""Helper to set up an ephemeral isolated HOME for --lean mode sessions.

Claude Code reads its config from $HOME/.claude/ and performs a few
self-checks (install method, theme, first-run setup) during launch.
Pointing HOME at a fully blank directory makes Claude Code re-run
onboarding and emit warnings about missing install directories. This
module creates a minimal scaffold that satisfies those self-checks
and inlines the user's CLAUDE.md (so their instructions are preserved)
while keeping the .claude config blank enough that plugins, skills,
MCP servers, and hooks don't get loaded.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

# Matches a full-line @<path> import directive. Claude Code's CLAUDE.md
# syntax for inlining another file's contents.
_IMPORT_PATTERN = re.compile(r"^@(\S+)\s*$", re.MULTILINE)

# Cap recursion when expanding imports, in case CLAUDE.md authors create
# accidental cycles (a.md → @b.md → @a.md).
_MAX_IMPORT_DEPTH = 3


def _expand_imports(
    content: str, base_dir: Path, real_home: Path, depth: int = 0
) -> str:
    """Inline-expand @<path> import directives in markdown content.

    Resolution rules for the path token after `@`:
      - starts with `~/`: relative to `real_home`
      - starts with `/`: absolute
      - otherwise: relative to `base_dir` (the dir containing the file
        that owns the import)

    If the target file does not exist or cannot be read, the original
    `@<path>` line is left in place so the user can see what was missed.
    Recursion is bounded by `_MAX_IMPORT_DEPTH`.
    """
    if depth >= _MAX_IMPORT_DEPTH:
        return content

    def replace(match: re.Match[str]) -> str:
        path_str = match.group(1)
        if path_str.startswith("~/"):
            target = real_home / path_str[2:]
        elif path_str.startswith("/"):
            target = Path(path_str)
        else:
            target = base_dir / path_str
        try:
            target = target.resolve()
            if not target.is_file():
                return match.group(0)
            imported = target.read_text()
        except (OSError, RuntimeError):
            return match.group(0)
        return _expand_imports(imported, target.parent, real_home, depth + 1)

    return _IMPORT_PATTERN.sub(replace, content)


def make_lean_home(base_cache_dir: Path, *, real_home: Path | None = None) -> Path:
    """Create an ephemeral HOME with a minimal scaffold.

    Returns the directory path. Caller is responsible for cleanup via
    cleanup_lean_home().

    The scaffold:
      - `.local/bin/` (empty dir) — satisfies Claude Code's installMethod
        check (the binary lives elsewhere; we only need the dir to exist)
      - `.claude/settings.json` with theme + onboarding state pre-set so
        Claude Code doesn't run the first-time theme picker
      - `.claude/CLAUDE.md` does NOT get inherited (lean session has no
        global instructions)

    If a real `~/.local/bin/claude` exists, it's symlinked into the
    lean-home's `.local/bin/` so Claude Code can introspect itself.
    """
    real_home = real_home or Path(os.environ.get("HOME", "~")).expanduser()

    home = base_cache_dir / f"lean-home-{os.getpid()}"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)

    # 1. .local/bin/ — install-method self-check looks for this directory.
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True, mode=0o755)

    # If the user has claude installed at ~/.local/bin/claude, symlink it
    # into the lean home so Claude Code can find itself for self-checks.
    real_claude = real_home / ".local" / "bin" / "claude"
    if real_claude.exists() or real_claude.is_symlink():
        try:
            (local_bin / "claude").symlink_to(real_claude.resolve())
        except (OSError, RuntimeError):
            # Symlink failure is non-fatal; the dir alone usually satisfies
            # the check.
            pass

    # 2. .claude/ with blank settings.json — no plugins, MCP, skills, hooks.
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps({}, indent=2))

    # 3. Copy ~/.claude.json (login state + onboarding + theme + per-project
    #    state) from the real HOME if it exists. Without this, Claude Code
    #    re-runs the onboarding wizard and asks for theme/login on every
    #    --lean session. Copying (not symlinking) means writes inside the
    #    lean session don't pollute the user's real state.
    real_claude_json = real_home / ".claude.json"
    if real_claude_json.exists() and real_claude_json.is_file():
        try:
            shutil.copy2(real_claude_json, home / ".claude.json")
        except OSError:
            # Best-effort; missing or unreadable is non-fatal but onboarding
            # may re-run.
            pass

    # 4. Inline-expand ~/.claude/CLAUDE.md and copy it into lean-home.
    #    Preserves the user's global instructions (personality, style
    #    preferences) while resolving @<path> imports to file contents so
    #    Claude Code does not prompt about external-import permission for
    #    every lean session.
    real_claude_md = real_home / ".claude" / "CLAUDE.md"
    if real_claude_md.exists() and real_claude_md.is_file():
        try:
            original = real_claude_md.read_text()
            expanded = _expand_imports(original, real_claude_md.parent, real_home)
            (claude_dir / "CLAUDE.md").write_text(expanded)
        except OSError:
            # Best-effort; without CLAUDE.md the session simply has no user
            # global instructions, which is the prior --lean behavior.
            pass

    return home


def cleanup_lean_home(home: Path) -> None:
    """Remove the ephemeral HOME directory. Idempotent."""
    if home.exists():
        try:
            shutil.rmtree(home)
        except OSError:
            pass
