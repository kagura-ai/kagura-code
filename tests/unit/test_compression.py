# tests/unit/test_compression.py
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pytest_httpserver import HTTPServer

from kagura_code.compression import (
    CompressionPolicy,
    CompressionState,
    LiteLLMSummarizer,
    approx_tokens,
    build_summary_message,
    find_tool_pairs,
    maybe_compress,
    pick_compress_range,
    render_messages_for_summary,
)


def test_approx_tokens_empty_list_returns_zero():
    assert approx_tokens([]) == 0


def test_approx_tokens_proportional_to_json_length():
    short = [{"role": "user", "content": "hi"}]
    long = [{"role": "user", "content": "x" * 3000}]
    short_t = approx_tokens(short)
    long_t = approx_tokens(long)
    assert long_t > short_t
    # 3000 chars of "x" should be at least ~900 tokens (3 chars/token floor)
    assert long_t >= 900


def test_approx_tokens_handles_non_ascii_without_crashing():
    msgs = [{"role": "user", "content": "こんにちは" * 200}]
    assert approx_tokens(msgs) > 0


def test_find_tool_pairs_matches_use_to_result():
    messages = [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "a.txt\nb.txt"},
        ]},
    ]
    pairs = find_tool_pairs(messages)
    assert pairs == [(1, 2, "toolu_1")]


def test_find_tool_pairs_skips_orphan_tool_use():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_X", "name": "Bash", "input": {}},
        ]},
    ]
    assert find_tool_pairs(messages) == []


def test_find_tool_pairs_handles_text_only_messages():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert find_tool_pairs(messages) == []


def test_find_tool_pairs_handles_string_content():
    messages = [{"role": "user", "content": "plain string content"}]
    assert find_tool_pairs(messages) == []


def _policy(window: int = 1_000_000) -> CompressionPolicy:
    return CompressionPolicy(
        threshold_tokens=50_000,
        threshold_cap_pct=0.4,
        model_context_window=window,
    )


def test_pick_compress_range_default_half():
    messages = [{"role": "user", "content": "x"} for _ in range(10)]
    start, end = pick_compress_range(messages, _policy())
    assert (start, end) == (0, 5)


def test_pick_compress_range_below_two_messages_returns_empty_range():
    messages = [{"role": "user", "content": "x"}]
    start, end = pick_compress_range(messages, _policy())
    assert (start, end) == (0, 0)


def test_pick_compress_range_trims_to_avoid_pair_split():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_A", "name": "X", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_A", "content": "ok"},
        ]},
        {"role": "assistant", "content": "fourth"},
    ]
    start, end = pick_compress_range(messages, _policy())
    assert (start, end) == (0, 1)


def test_pick_compress_range_custom_keep_recent_pct():
    messages = [{"role": "user", "content": "x"} for _ in range(10)]
    p = CompressionPolicy(
        threshold_tokens=50_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000, keep_recent_pct=0.3,
    )
    start, end = pick_compress_range(messages, p)
    assert (start, end) == (0, 7)


def test_render_messages_string_content():
    messages = [{"role": "user", "content": "hello world"}]
    out = render_messages_for_summary(messages)
    assert "[user]" in out
    assert "hello world" in out


def test_render_messages_text_block():
    messages = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    out = render_messages_for_summary(messages)
    assert "[assistant]" in out
    assert "hi" in out


def test_render_messages_includes_tool_use_metadata():
    messages = [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_Z", "name": "Bash", "input": {"command": "ls"}},
    ]}]
    out = render_messages_for_summary(messages)
    assert "tool_use" in out
    assert "Bash" in out
    assert "ls" in out


def test_render_messages_truncates_huge_tool_result():
    huge = "x" * 5000
    messages = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_Q", "content": huge},
    ]}]
    out = render_messages_for_summary(messages)
    assert "tool_result" in out
    assert "xxx" in out
    assert len(out) < 1200


def test_build_summary_message_shape():
    msg = build_summary_message("here is a summary")
    assert msg["role"] == "user"
    assert msg["content"][0]["type"] == "text"
    assert "Previous conversation summary" in msg["content"][0]["text"]
    assert "here is a summary" in msg["content"][0]["text"]


@pytest.mark.asyncio
async def test_litellm_summarizer_happy_path(httpserver: HTTPServer):
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_json({
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "claude-qwen3-5",
        "choices": [
            {"index": 0, "finish_reason": "stop",
             "message": {"role": "assistant", "content": "the summary"}}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })

    s = LiteLLMSummarizer(
        proxy_url=httpserver.url_for(""),
        model="claude-qwen3-5",
        master_key="dummy",
    )
    out = await s.summarize("anything")
    assert out == "the summary"


@pytest.mark.asyncio
async def test_litellm_summarizer_propagates_master_key(httpserver: HTTPServer):
    received_auth: dict[str, str] = {}

    def capture(req):
        received_auth["value"] = req.headers.get("Authorization") or ""
        from werkzeug.wrappers import Response
        return Response(
            '{"choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"ok"}}]}',
            content_type="application/json",
        )

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_handler(capture)

    s = LiteLLMSummarizer(
        proxy_url=httpserver.url_for(""), model="m", master_key="secret-key",
    )
    await s.summarize("x")
    assert received_auth["value"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_litellm_summarizer_raises_on_5xx(httpserver: HTTPServer, monkeypatch):
    async def _noop_sleep(_s: float) -> None:
        pass
    monkeypatch.setattr("kagura_code.compression.asyncio.sleep", _noop_sleep)

    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_data(
        "boom", status=500,
    )
    s = LiteLLMSummarizer(
        proxy_url=httpserver.url_for(""), model="m", master_key="x",
    )
    with pytest.raises(Exception):  # noqa: B017 — any httpx error type
        await s.summarize("x")


@pytest.mark.asyncio
async def test_litellm_summarizer_retries_once_on_http_error(
    httpserver: HTTPServer, monkeypatch
):
    """First call returns 503, second returns 200 — summarize returns success."""
    async def _noop_sleep(_s: float) -> None:
        pass
    monkeypatch.setattr("kagura_code.compression.asyncio.sleep", _noop_sleep)

    call_count = {"n": 0}

    def handler(_req):
        from werkzeug.wrappers import Response
        call_count["n"] += 1
        if call_count["n"] == 1:
            return Response("transient", status=503)
        import json
        return Response(
            json.dumps({"choices": [{"finish_reason": "stop",
                                     "message": {"role": "assistant", "content": "ok"}}]}),
            content_type="application/json",
        )

    httpserver.expect_request("/v1/chat/completions").respond_with_handler(handler)
    s = LiteLLMSummarizer(proxy_url=httpserver.url_for(""), model="m", master_key="x")
    out = await s.summarize("text")
    assert out == "ok"
    assert call_count["n"] == 2


def test_compression_state_defaults():
    s = CompressionState()
    assert s.summary_text is None
    assert s.compressed_until_idx == 0
    assert s.compress_task is None


class FakeSummarizer:
    def __init__(
        self,
        response: str = "FAKE SUMMARY",
        *,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.response = response
        self.raise_on_call = raise_on_call
        self.calls: list[str] = []

    async def summarize(self, text: str, *, max_tokens: int = 4096) -> str:
        self.calls.append(text)
        if self.raise_on_call:
            raise self.raise_on_call
        return self.response


@pytest.mark.asyncio
async def test_maybe_compress_below_threshold_returns_input_unchanged():
    messages: list[dict[str, Any]] = [{"role": "user", "content": "small"}]
    state = CompressionState()
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=50_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    out = await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert out == messages
    assert summ.calls == []
    assert state.compress_task is None


@pytest.mark.asyncio
async def test_maybe_compress_above_threshold_fires_background_task():
    big = "x" * 500   # roughly 166 tokens per message at 3 chars/token
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )

    out = await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert out == messages  # turn returns uncompressed
    assert state.compress_task is not None
    await state.compress_task  # let it finish for assertion
    assert state.summary_text == "FAKE SUMMARY"
    assert state.compressed_until_idx == 500  # default 50% of 1000


@pytest.mark.asyncio
async def test_maybe_compress_does_not_fire_when_task_pending():
    big = "x" * 500
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()

    async def never_completes() -> None:
        await asyncio.sleep(60)
    state.compress_task = asyncio.create_task(never_completes())

    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    try:
        await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
        assert summ.calls == []  # no new call
    finally:
        state.compress_task.cancel()


@pytest.mark.asyncio
async def test_maybe_compress_applies_cached_summary_on_next_call():
    state = CompressionState(
        summary_text="cached summary",
        compressed_until_idx=3,
    )
    # 5 messages, first 3 should be replaced by summary
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"old-{i}"} for i in range(3)
    ] + [
        {"role": "assistant", "content": "recent"},
        {"role": "user", "content": "newer"},
    ]
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=50_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    out = await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert len(out) == 3   # 1 summary + 2 recent
    assert "cached summary" in out[0]["content"][0]["text"]
    assert out[1]["content"] == "recent"
    assert out[2]["content"] == "newer"
    assert summ.calls == []   # no new summarizer call needed


@pytest.mark.asyncio
async def test_maybe_compress_invalidates_cache_when_messages_shrink():
    state = CompressionState(
        summary_text="cached summary",
        compressed_until_idx=10,
    )
    # client now sends only 5 messages — history shrank (e.g. /compact reset)
    messages: list[dict[str, Any]] = [{"role": "user", "content": "x"} for _ in range(5)]
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=50_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    out = await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert state.summary_text is None
    assert state.compressed_until_idx == 0
    assert out == messages   # no summary applied


@pytest.mark.asyncio
async def test_maybe_compress_summarizer_exception_keeps_state_clean():
    big = "x" * 500
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()
    summ = FakeSummarizer(raise_on_call=RuntimeError("upstream is down"))
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert state.compress_task is not None
    await state.compress_task
    assert state.summary_text is None       # unchanged
    assert state.compressed_until_idx == 0  # unchanged


@pytest.mark.asyncio
async def test_maybe_compress_empty_summary_keeps_state_clean():
    big = "x" * 500
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()
    summ = FakeSummarizer(response="   ")   # whitespace only
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    assert state.compress_task is not None
    await state.compress_task
    assert state.summary_text is None
    assert state.compressed_until_idx == 0


@pytest.mark.asyncio
async def test_maybe_compress_second_compression_stores_original_frame_index():
    """After a session already has a cached summary, the next compression must
    record `compressed_until_idx` in the original-list frame, not the
    forwarded (post-cache) frame. The forwarded list starts with one summary
    message replacing N original messages, so a forwarded-frame index of K
    maps to original index (old_until + K - 1).
    """
    big = "x" * 500
    # Original conversation has 100 messages. First 30 are already summarized.
    original: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(100)
    ]
    state = CompressionState(
        summary_text="prior summary",
        compressed_until_idx=30,
    )
    summ = FakeSummarizer(response="next summary")
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )

    await maybe_compress(original, state=state, policy=policy, summarizer=summ)
    assert state.compress_task is not None
    await state.compress_task

    # Forwarded list = [summary, m30..m99] = 71 entries.
    # pick_compress_range cuts at 50% → end = 35 in forwarded frame.
    # Translation: original_end = old_until(30) + end(35) - 1 = 64.
    # That means messages m0..m63 are now covered by the new summary, and
    # the next request should serve original[64:] as the uncompressed tail.
    assert state.summary_text == "next summary"
    assert state.compressed_until_idx == 64
    # The summarizer must receive the prior summary as preamble (not as a
    # synthetic conversation turn) AND must not see the literal
    # "[Previous conversation summary]" framing the middleware uses for
    # forwarding. This guards against summary-of-summary degradation.
    assert "prior summary" in summ.calls[0]
    assert "[Previous conversation summary]" not in summ.calls[0]


@pytest.mark.asyncio
async def test_maybe_compress_clears_compress_task_on_completion():
    """After a background task completes (success OR failure), state.compress_task
    must be cleared so the Task object doesn't accumulate references for the
    rest of the session's lifetime.
    """
    big = "x" * 500
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    pending = state.compress_task
    assert pending is not None
    await pending
    assert state.compress_task is None


@pytest.mark.asyncio
async def test_maybe_compress_clears_compress_task_on_failure():
    big = "x" * 500
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": big} for _ in range(1000)
    ]
    state = CompressionState()
    summ = FakeSummarizer(raise_on_call=RuntimeError("upstream down"))
    policy = CompressionPolicy(
        threshold_tokens=10_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    await maybe_compress(messages, state=state, policy=policy, summarizer=summ)
    pending = state.compress_task
    assert pending is not None
    await pending
    assert state.compress_task is None


@pytest.mark.asyncio
async def test_maybe_compress_invalidates_cache_on_exact_length_equality():
    """When the client re-sends a history exactly equal in length to
    `compressed_until_idx`, the uncompressed tail is empty; forwarding just
    the synthetic summary with no real turns produces zero-context output.
    Cache must be invalidated for `<=`, not only `<`.
    """
    state = CompressionState(
        summary_text="stale summary",
        compressed_until_idx=10,
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": "x"} for _ in range(10)]
    summ = FakeSummarizer()
    policy = CompressionPolicy(
        threshold_tokens=50_000, threshold_cap_pct=0.4,
        model_context_window=1_000_000,
    )
    out = await maybe_compress(messages, state=state, policy=policy, summarizer=summ)

    assert state.summary_text is None
    assert state.compressed_until_idx == 0
    assert out == messages
    assert summ.calls == []
