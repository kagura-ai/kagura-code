"""Config loading and validation.

Resolution priority (highest first):
  1. --config <path>
  2. $KAGURA_CODE_CONFIG
  3. ~/.config/kagura-code/config.toml
  4. packaged default (_vendor/default_config.toml)

User [[models]] entries with matching alias override defaults.
New aliases are additive. [ollama_cloud] fields are shallow-merged.

Auth note: kagura-code targets the local Ollama daemon by default
(http://localhost:11434/v1), which handles cloud model auth via
`ollama signin`. No API key is needed at this layer.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import ModelSpec


class ConfigError(ValueError):
    """Raised for any config load/parse/validate failure."""


@dataclass(frozen=True)
class OllamaCloudConfig:
    api_base: str


@dataclass(frozen=True)
class RtkConfig:
    enabled: str  # "auto" | "true" | "false"


@dataclass(frozen=True)
class Config:
    default_model: str
    models: list[ModelSpec]
    ollama_cloud: OllamaCloudConfig
    rtk: RtkConfig = field(default_factory=lambda: RtkConfig(enabled="auto"))
    source_paths: list[Path] = field(default_factory=list)


def _load_default() -> dict[str, Any]:
    resource = files("kagura_code._vendor").joinpath("default_config.toml")
    with resource.open("rb") as f:
        return tomllib.load(f)


def _load_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid config at {path}: {e}") from e


def _resolve_path(explicit: Path | None) -> tuple[Path | None, list[Path]]:
    """Return (user_config_path_or_None, list_of_searched_paths)."""
    searched: list[Path] = []
    if explicit is not None:
        searched.append(explicit)
        return (explicit if explicit.exists() else None, searched)
    env_path = os.environ.get("KAGURA_CODE_CONFIG")
    if env_path:
        p = Path(env_path)
        searched.append(p)
        if p.exists():
            return (p, searched)
    home = Path(os.environ.get("HOME", "~")).expanduser()
    user = home / ".config" / "kagura-code" / "config.toml"
    searched.append(user)
    if user.exists():
        return (user, searched)
    return (None, searched)


def _merge(default: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Merge user config on top of default.

    [[models]] entries are merged by alias: same alias -> user wins.
    New aliases are additive. [default] and [ollama_cloud] are field-merged shallowly.
    """
    out: dict[str, Any] = {
        "default": {**default.get("default", {}), **user.get("default", {})},
        "ollama_cloud": {**default.get("ollama_cloud", {}), **user.get("ollama_cloud", {})},
        "rtk": {**default.get("rtk", {}), **user.get("rtk", {})},
    }
    by_alias: dict[str, dict[str, Any]] = {m["alias"]: m for m in default.get("models", [])}
    for m in user.get("models", []):
        by_alias[m["alias"]] = m
    out["models"] = list(by_alias.values())
    return out


def load_config(explicit_path: Path | None) -> Config:
    user_path, _searched = _resolve_path(explicit_path)
    if explicit_path is not None and user_path is None:
        raise ConfigError(f"config file not found: {explicit_path}")
    default = _load_default()
    if explicit_path is not None:
        # Explicit path is used as a standalone config — no merging with defaults.
        merged = _load_file(user_path) if user_path else {}
    else:
        user = _load_file(user_path) if user_path else {}
        merged = _merge(default, user)

    try:
        default_model = merged["default"]["model"]
    except KeyError as e:
        raise ConfigError("config missing [default].model") from e

    try:
        oc = OllamaCloudConfig(
            api_base=merged["ollama_cloud"]["api_base"],
        )
    except KeyError as e:
        raise ConfigError(f"config missing [ollama_cloud].{e.args[0]}") from e

    models: list[ModelSpec] = []
    for entry in merged["models"]:
        try:
            models.append(
                ModelSpec(
                    alias=entry["alias"],
                    display_name=entry["display_name"],
                    ollama_model=entry["ollama_model"],
                    context_window=int(entry["context_window"]),
                    max_output_tokens=int(entry["max_output_tokens"]),
                    recommended_use=str(entry.get("recommended_use", "")),
                )
            )
        except (KeyError, ValueError, TypeError) as e:
            raise ConfigError(f"invalid model entry {entry.get('alias', '?')}: {e}") from e

    rtk_section = merged.get("rtk", {})
    rtk = RtkConfig(enabled=str(rtk_section.get("enabled", "auto")))

    sources = [user_path] if user_path else []
    return Config(
        default_model=default_model,
        models=models,
        ollama_cloud=oc,
        rtk=rtk,
        source_paths=sources,
    )
