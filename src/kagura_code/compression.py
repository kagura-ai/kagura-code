"""Context compression for the on-demand middleware.

See docs/superpowers/specs/2026-05-22-context-compression-design.md for the
full design rationale, the threshold formula, and the tool_use pairing rules.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompressionPolicy:
    """Trigger thresholds and range-selection knobs.

    `threshold_tokens` and `threshold_cap_pct * model_context_window` are
    combined via min() — the smaller of the two wins. keep_recent_pct is the
    fraction of messages preserved verbatim at the tail.
    """
    threshold_tokens: int
    threshold_cap_pct: float
    model_context_window: int
    keep_recent_pct: float = 0.5


@dataclass
class CompressionState:
    """Per-session mutable state. Stored inside SessionState.compression.

    `compress_task` is the in-flight background asyncio.Task (if any).
    Tasks are fire-and-forget; the orchestrator does not await them.
    """
    summary_text: str | None = None
    compressed_until_idx: int = 0
    compress_task: asyncio.Task[None] | None = None


class Summarizer(Protocol):
    """Backend-agnostic summarizer.

    Future implementations could target Anthropic's API directly, an Ollama
    daemon, or any other chat-completion endpoint without changing the
    compression algorithm.
    """
    async def summarize(self, text: str, *, max_tokens: int = 4096) -> str: ...


class LiteLLMSummarizer:
    """v1 implementation: hits a LiteLLM proxy /v1/chat/completions.

    Same wire format as ToolRouter: Bearer master_key auth, temperature 0,
    plain text output expected in choices[0].message.content.

    Single retry on transient HTTP errors; falls back to pass-through if
    both attempts fail.
    """

    _PROMPT = (
        "You are summarizing the older portion of a developer conversation so a"
        " coding assistant can continue without re-reading the full history.\n\n"
        "Preserve:\n"
        "- File paths, function names, decisions, errors and their resolutions\n"
        "- Tool calls and their outcomes (e.g., \"Bash tail log → 'connection refused'\")\n\n"
        "Drop:\n"
        "- Greetings, retries, exploratory dead ends, redundant outputs\n\n"
        "Output: plain markdown, no preamble, no commentary about the task.\n\n"
        "<conversation>\n{rendered}\n</conversation>"
    )

    def __init__(
        self,
        *,
        proxy_url: str,
        model: str,
        master_key: str,
        timeout_s: float = 180.0,
    ) -> None:
        # 180s default: qwen3.5:397b summarizing ~50K tokens routinely takes
        # 60-120s end-to-end (Ollama Cloud queue + generation). The earlier
        # 60s default surfaced as `summarizer failed (ReadTimeout(''))` on
        # cold cloud routes. Override via KAGURA_CODE_SUMMARIZER_TIMEOUT.
        self.proxy_url = proxy_url.rstrip("/")
        self.model = model
        self.master_key = master_key
        self.timeout_s = timeout_s

    async def summarize(self, text: str, *, max_tokens: int = 4096) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": self._PROMPT.format(rendered=text)}],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.master_key}"}
        data: dict[str, Any] | None = None
        # One retry on transient cloud timeouts; pass-through fallback still active if both fail.
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as c:
                    r = await c.post(
                        f"{self.proxy_url}/v1/chat/completions", json=body, headers=headers,
                    )
                    r.raise_for_status()
                    data = r.json()
                break  # success — exit retry loop
            except httpx.HTTPError:
                if attempt == 1:
                    await asyncio.sleep(5.0)
                    continue
                raise  # second attempt failed — let _run_compression handle
        if data is None:
            return ""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""
        if not isinstance(content, str):
            return ""
        return content


def approx_tokens(messages: list[dict[str, Any]]) -> int:
    """Conservative token-count estimate: 3 chars per token.

    Real tokenizers run ~3.5-4 for English and ~2-2.5 for code-heavy text;
    3 is the floor we treat as "could be at least this many." Overestimating
    makes the threshold fire sooner, which is the safe direction.
    """
    if not messages:
        return 0
    total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    return total_chars // 3


def find_tool_pairs(messages: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """Return [(use_msg_idx, result_msg_idx, tool_use_id), ...].

    Orphan tool_use blocks (no matching tool_result yet) are dropped from the
    output so callers never accidentally split an in-flight call.
    """
    pending: dict[str, int] = {}
    out: list[tuple[int, int, str]] = []
    for i, m in enumerate(messages):
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "tool_use":
                tid = b.get("id")
                if isinstance(tid, str):
                    pending[tid] = i
            elif btype == "tool_result":
                tid = b.get("tool_use_id")
                if isinstance(tid, str) and tid in pending:
                    out.append((pending.pop(tid), i, tid))
    return out


def pick_compress_range(
    messages: list[dict[str, Any]], policy: CompressionPolicy
) -> tuple[int, int]:
    """Return [start, end) indices of messages to compress.

    Default cut is at (1 - keep_recent_pct) of the message count. If that cut
    would split a tool_use/tool_result pair, the cut is moved earlier (never
    later) so the pair stays intact on the uncompressed side.
    """
    total = len(messages)
    cut = int(total * (1.0 - policy.keep_recent_pct))
    # Process pairs with the largest result_idx first. A later pair can pull
    # `cut` to its use_idx, which may then put an earlier pair's result_idx
    # past the cut even though the earlier pair was already checked.  Sorting
    # by result_idx descending makes one pass sufficient.
    pairs = sorted(find_tool_pairs(messages), key=lambda p: p[1], reverse=True)
    for use_idx, result_idx, _ in pairs:
        if use_idx < cut <= result_idx:
            cut = use_idx
    return (0, cut)


def render_messages_for_summary(messages: list[dict[str, Any]]) -> str:
    """Flatten messages to a labeled transcript suitable for a summarizer prompt.

    Individual tool_result bodies are truncated at 1000 chars so a single
    enormous result cannot dominate the rendered transcript.
    """
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            lines.append(f"[{role}] {content}")
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "text":
                lines.append(f"[{role}] {b.get('text', '')}")
            elif btype == "tool_use":
                name = b.get("name", "?")
                tid = str(b.get("id", "?"))[:8]
                input_str = json.dumps(b.get("input", {}), ensure_ascii=False)[:500]
                lines.append(f"[{role}] (tool_use {tid}: {name} input={input_str})")
            elif btype == "tool_result":
                result = b.get("content", "")
                if isinstance(result, list):
                    result = " ".join(
                        str(x.get("text", "")) for x in result
                        if isinstance(x, dict)
                    )
                result_str = str(result)[:1000]
                tid = str(b.get("tool_use_id", "?"))[:8]
                lines.append(f"[{role}] (tool_result for {tid}: {result_str})")
    return "\n".join(lines)


def build_summary_message(summary: str) -> dict[str, Any]:
    """Wrap a summary string into the user-role text block that replaces the
    compressed prefix of `messages` when the middleware forwards a request.
    """
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": f"[Previous conversation summary]\n\n{summary}",
        }],
    }


def _should_fire(
    forwarded: list[dict[str, Any]],
    policy: CompressionPolicy,
    state: CompressionState,
) -> bool:
    """Trigger check on the FORWARDED list so the cached summary's own size
    is counted toward the budget; measuring only the uncompressed tail
    silently let the daemon receive payloads exceeding the cap by the
    summary's contribution every turn.
    """
    if state.compress_task is not None and not state.compress_task.done():
        return False
    approx = approx_tokens(forwarded)
    cap = int(policy.model_context_window * policy.threshold_cap_pct)
    return approx > min(policy.threshold_tokens, cap)


async def maybe_compress(
    messages: list[dict[str, Any]],
    *,
    state: CompressionState,
    policy: CompressionPolicy,
    summarizer: Summarizer,
) -> list[dict[str, Any]]:
    """Return possibly-compressed messages.

    1. Invalidate the cache if `len(messages)` is at or below
       `compressed_until_idx` (no uncompressed tail to keep).
    2. Build the forwarded list (cached summary prepended when available).
    3. Decide whether to fire against the forwarded list so the cached
       summary's size is part of the budget.
    4. Exclude the synthetic summary message from target_slice and pass the
       prior summary text to the background task as preamble — feeding the
       synthetic message back into the summarizer produces summary-of-summary
       and progressively erases earlier conversation history.
    5. Schedule a background summarization task whose `end_idx` is
       translated back to the original-list frame before being stored.
    """
    if (
        state.summary_text is not None
        and len(messages) <= state.compressed_until_idx
    ):
        state.summary_text = None
        state.compressed_until_idx = 0

    cached_summary = state.summary_text
    old_until = state.compressed_until_idx
    has_cache = cached_summary is not None and old_until > 0
    if has_cache and cached_summary is not None:
        forwarded = [
            build_summary_message(cached_summary),
            *messages[old_until:],
        ]
    else:
        forwarded = messages

    if not _should_fire(forwarded, policy, state):
        return forwarded

    start, end = pick_compress_range(forwarded, policy)
    slice_start = max(start, 1) if has_cache else start
    if end - slice_start < 2:
        return forwarded

    target_slice = list(forwarded[slice_start:end])
    # original-frame end: forwarded[e] (exclusive) maps to old_until + e - 1
    # when forwarded[0] is the cached summary; without a cache, the index
    # frames coincide and end maps directly.
    original_end = old_until + end - 1 if has_cache else end

    prior_summary = cached_summary if has_cache else None
    state.compress_task = asyncio.create_task(
        _run_compression(target_slice, original_end, state, summarizer, prior_summary)
    )
    return forwarded


async def _run_compression(
    target_slice: list[dict[str, Any]],
    end_idx: int,
    state: CompressionState,
    summarizer: Summarizer,
    prior_summary: str | None = None,
) -> None:
    """Background task body. Updates state in place on success; never raises.

    When `prior_summary` is set, it is prepended to the rendered transcript
    as labeled preamble so the summarizer treats it as known context rather
    than as something to summarize. This preserves earlier conversation
    history across multiple compression cycles without recursively nesting
    `[Previous conversation summary]` blocks.
    """
    try:
        rendered = render_messages_for_summary(target_slice)
        if prior_summary:
            rendered = (
                "Earlier summary (preserve key facts; extend with the new turns below):\n"
                f"{prior_summary}\n\n"
                f"New turns:\n{rendered}"
            )
        summary = await summarizer.summarize(rendered, max_tokens=4096)
        if summary.strip():
            state.summary_text = summary.strip()
            state.compressed_until_idx = end_idx
            log.info(
                "compression: done, summary=%d chars, until_idx=%d",
                len(summary), end_idx,
            )
        else:
            log.warning("compression: summarizer returned empty; state unchanged")
    except Exception as e:
        log.warning("compression: summarizer failed (%r); pass-through", e)
    finally:
        # Release the completed Task object so it doesn't accumulate references
        # for the rest of the session's lifetime. _should_fire already treats
        # `task is None` and `task.done()` identically.
        state.compress_task = None
