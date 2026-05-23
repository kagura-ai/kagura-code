"""kagura-code CLI entry point.

Currently a stub that only supports `--version`. Phase 2 will port the
real launcher (config loading, LiteLLM proxy startup, on-demand middleware,
Claude Code subprocess) from the prior `ollama-code` codebase.
"""
from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    name="kagura-code",
    help="Run Claude Code CLI against non-Anthropic LLM backends.",
    add_completion=False,
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kagura-code {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show kagura-code version and exit.",
    ),
) -> None:
    """Top-level entry point. Phase 1 skeleton: --version only."""
    # Phase 1 stub. Phase 2 will dispatch to the real runner.
    typer.echo(
        "kagura-code skeleton — no runtime yet. "
        "See https://github.com/kagura-ai/kagura-code for status."
    )
