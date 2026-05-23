"""Async client for the lightweight router model.

The router classifies which non-core tools a request is likely to need,
so the main model only receives those tool schemas. The router itself runs
through the same LiteLLM proxy as the primary model (using an existing
alias from the configured model list).

On any error (network, timeout, bad JSON, HTTP non-2xx), `predict()` returns
the special sentinel value `ToolRouter.FALLBACK_ALL` so callers can switch to
sending the full tool list.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Final

import httpx

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_PROMPT_TEMPLATE = (
    "You are a tool-routing classifier. Given the user request below, return ONLY a JSON"
    " list of tool names that will likely be needed to satisfy the request."
    " Do not explain. Do not include tools that are almost certainly unneeded.\n\n"
    "Available non-core tools (full definitions withheld):\n{catalog_stub}\n\n"
    "Request: {user_message}\n\n"
    'Respond with ONLY the JSON list, e.g. ["tool_a", "tool_b"].'
    " If no non-core tool is needed, respond with []."
)


class ToolRouter:
    FALLBACK_ALL: Final[str] = "__fallback_all__"

    def __init__(
        self,
        *,
        proxy_url: str,
        router_model: str,
        master_key: str,
        timeout_s: float = 5.0,
    ) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.router_model = router_model
        self.master_key = master_key  # LiteLLM proxy master key for Authorization header.
        self.timeout_s = timeout_s

    async def predict(self, *, user_message: str, catalog_stub: str) -> list[str] | str:
        """Return predicted tool names or `FALLBACK_ALL` sentinel on any error."""
        if not catalog_stub.strip():
            return []
        prompt = _PROMPT_TEMPLATE.format(
            catalog_stub=catalog_stub,
            user_message=user_message[:1000],
        )
        body = {
            "model": self.router_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 100,
        }
        headers = {"Authorization": f"Bearer {self.master_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as c:
                r = await c.post(
                    f"{self.proxy_url}/v1/chat/completions", json=body, headers=headers
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            # Use %r so the exception class name is in the log even when the
            # message is empty (some httpx network errors have str(e) == "").
            log.warning("router: HTTP error (%r); falling back to full tool list", e)
            return self.FALLBACK_ALL
        except ValueError as e:
            log.warning("router: response not JSON (%r); falling back", e)
            return self.FALLBACK_ALL

        try:
            content = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as e:
            log.warning("router: response malformed (%s); falling back", e)
            return self.FALLBACK_ALL

        m = _FENCE_RE.match(content)
        if m:
            content = m.group(1).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            log.warning(
                "router: output not JSON (%s); content=%r; falling back",
                e,
                content[:200],
            )
            return self.FALLBACK_ALL

        if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
            log.warning(
                "router: output not list[str]; got %r; falling back",
                type(parsed).__name__,
            )
            return self.FALLBACK_ALL

        return parsed
