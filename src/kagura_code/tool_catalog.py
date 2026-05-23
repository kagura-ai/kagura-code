"""Parse + filter Anthropic tool schemas for the on-demand router.

The catalog snapshots the tool schemas attached to a single /v1/messages
request, then produces filtered subsets (for forwarding to the primary
model) and compact stub text (for the router-model prompt).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# These are Claude Code's built-in core tools that appear in nearly every
# session. Keeping them eagerly available avoids
# router miss → full-load promotion noise the user would otherwise see as
# `on-demand: miss — model called 'X' which was not in the filtered tool list`.
CORE_TOOLS: frozenset[str] = frozenset({
    "Read",
    "Edit",
    "Write",
    "Bash",
    "Glob",
    "Grep",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "NotebookRead",
    "ExitPlanMode",
    "BashOutput",
    "KillShell",
    "Skill",
    "AskUserQuestion",
})


@dataclass
class ToolCatalog:
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_request(cls, body: dict[str, Any]) -> ToolCatalog:
        tools = body.get("tools") or []
        schemas: dict[str, dict[str, Any]] = {}
        for t in tools:
            name = t.get("name")
            if not name or not isinstance(name, str):
                continue
            schemas[name] = t
        return cls(schemas=schemas)

    def all_names(self) -> list[str]:
        return list(self.schemas.keys())

    def non_core_names(self) -> list[str]:
        return [n for n in self.schemas if n not in CORE_TOOLS]

    def stub_text(self) -> str:
        """Compact catalog for the router prompt.

        Includes one line per non-core tool: `- name: short description`.
        Core tools are omitted because they are always included in the final
        filtered set regardless of router output.
        """
        lines: list[str] = []
        for name in sorted(self.non_core_names()):
            schema = self.schemas[name]
            raw_desc = schema.get("description") or ""
            desc = raw_desc.strip().splitlines()[0] if raw_desc else ""
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"- {name}: {desc}" if desc else f"- {name}")
        return "\n".join(lines)

    def filter(self, names: list[str]) -> list[dict[str, Any]]:
        """Return full schemas for the given names (silently drops unknowns)."""
        return [self.schemas[n] for n in names if n in self.schemas]

    def filter_with_core(self, names: list[str]) -> list[dict[str, Any]]:
        """Return CORE_TOOLS union named tools (full schemas).

        Preserves the original request's tool order for stability.
        """
        wanted = set(names)
        for core in CORE_TOOLS:
            if core in self.schemas:
                wanted.add(core)
        ordered = [n for n in self.schemas if n in wanted]
        return [self.schemas[n] for n in ordered]

    def all(self) -> list[dict[str, Any]]:
        """Return every schema (fallback path)."""
        return list(self.schemas.values())
