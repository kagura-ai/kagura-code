"""Middleware subpackage: FastAPI app + subprocess lifecycle.

The middleware sits between Claude Code and the LiteLLM proxy. It owns
session-scoped state (tool filtering, context compression) and rewrites
Authorization headers / model aliases per request.
"""
from .app import build_app, extract_session_id
from .proc import MiddlewareHandle, MiddlewareManager

__all__ = [
    "MiddlewareHandle",
    "MiddlewareManager",
    "build_app",
    "extract_session_id",
]
